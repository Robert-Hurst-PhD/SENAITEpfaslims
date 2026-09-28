# Configurability audit

`tools/audit_configurable.py` · 118 profile keys examined

## Dead config (0)

The UI writes it; no engine code reads it. Editing it changes nothing.

None.

## Unreachable config (0)

The engine reads it; no UI writes it. The lab cannot change it.

None.

## UI-only config (2)

An editor writes it and reads it back; nothing downstream consumes it. Looks alive, changes nothing.

| key | evidence |
|---|---|
| `run_template` | `src/senaite/pfas/browser/run_builder.py:254` |
| `run_template.bracket_qc` | `src/senaite/pfas/browser/run_builder.py:259`<br>`src/senaite/pfas/browser/run_builder.py:266`<br>`src/senaite/pfas/browser/run_builder.py:633` |

## Derived — not findings (3)

| key | derived by |
|---|---|
| `display_analyte_set` | method_profile_store.py:1253 — from the master set |
| `master_analyte_set` | method_profile_store.py:1239 — from the Method's services |
| `matrix_uid_map` | method_profile_store.py:1117 — from the Sample Type UIDs |

## Split keys (0)

None.

## Hardcoded lab values (107)

| location | kind | line |
|---|---|---|
| `pfas_pipeline/barcode.py:28` | lab table in code | `DEFAULT_SHELF_LIFE_DAYS = {` |
| `pfas_pipeline/constants.py:50` | lab table in code | `_DEFAULT_CRITERIA = {` |
| `pfas_pipeline/egad_edd.py:94` | lab table in code | `_LAB_REQUIRED = frozenset([` |
| `pfas_pipeline/egad_edd.py:103` | lab table in code | `_QC_REQUIRED = frozenset([` |
| `pfas_pipeline/egad_edd.py:114` | lab table in code | `DEFAULT_QUALIFIER_MAP = {` |
| `pfas_pipeline/egad_edd.py:129` | lab table in code | `DEFAULT_QC_TYPE_MAP = {` |
| `pfas_pipeline/egad_edd.py:152` | lab table in code | `METHOD_TEST_CODES = {` |
| `pfas_pipeline/injection_builder.py:23` | lab table in code | `FDA_CAL_LEVELS = [` |
| `pfas_pipeline/injection_builder.py:39` | lab table in code | `EPA537_CAL_LEVELS = [` |
| `pfas_pipeline/injection_builder.py:48` | lab table in code | `EPA537_QCS = [("537-QCS-1", "80/320 ppt"), ("537-QCS-2", "20/80 ppt")]` |
| `pfas_pipeline/method_profiles.py:169` | lab table in code | `_DEFAULT_PROFILE_CACHE = {` |
| `pfas_pipeline/method_profiles.py:441` | lab table in code | `_OVERLAY_PATHS = {` |
| `pfas_pipeline/method_profiles.py:475` | lab table in code | `_CRITERIA_KEYS_BY_OVERLAY_KEY = {` |
| `pfas_pipeline/method_profiles.py:904` | acceptance value inlined as a fallback | `confirm_pct_diff_max=conf.get("confirm_pct_diff_max", 20.0),` |
| `pfas_pipeline/method_profiles.py:1030` | acceptance value inlined as a fallback | `fallbacks of the form tier.get("recovery_min", 40.0), so a profile that was` |
| `pfas_pipeline/method_profiles.py:1043` | lab table in code | `_TIER_STRUCTURAL_KEYS = frozenset([` |
| `pfas_pipeline/method_profiles.py:1362` | lab table in code | `_PROFILES = {` |
| `pfas_pipeline/method_profiles.py:1369` | lab table in code | `_ALIASES = {` |
| `pfas_pipeline/models.py:346` | lab table in code | `BATCH_QC_REQUIREMENTS = [` |
| `pfas_pipeline/run_queue.py:808` | lab table in code | `_CHECK_KINDS = {` |
| `pfas_pipeline/vendor_profiles.py:25` | lab table in code | `WATERS_MASSLYNX = {` |
| `pfas_pipeline/vendor_profiles.py:55` | lab table in code | `AGILENT_MASSHUNTER = {` |
| `pfas_pipeline/vendor_profiles.py:86` | lab table in code | `SCIEX_OS = {` |
| `pfas_pipeline/vendor_profiles.py:119` | lab table in code | `NATIVE_FDA_CALCULATOR = {` |
| `src/senaite/pfas/analyte_reference.py:27` | lab table in code | `NATIVE_ANALYTES = [` |
| `src/senaite/pfas/analyte_reference.py:114` | lab table in code | `METHODS = [` |
| `src/senaite/pfas/analyte_reference.py:125` | lab table in code | `SAMPLE_TYPES = [` |
| `src/senaite/pfas/analyte_reference.py:144` | lab table in code | `CONTAINERS = [` |
| `src/senaite/pfas/analyte_reference.py:163` | lab table in code | `STORAGE_LOCATIONS = [` |
| `src/senaite/pfas/analyte_reference.py:175` | lab table in code | `PRESERVATIONS = [` |
| `src/senaite/pfas/analyte_reference.py:188` | lab table in code | `CAL_LADDERS = {` |
| `src/senaite/pfas/analytes.py:10` | lab table in code | `PFAS_ANALYTES = [` |
| `src/senaite/pfas/analytes.py:63` | lab table in code | `IS_MRM = {` |
| `src/senaite/pfas/analytes.py:108` | lab table in code | `INJECTION_PATTERNS = [` |
| `src/senaite/pfas/analytes.py:123` | lab table in code | `QC_TYPE_CODES = {` |
| `src/senaite/pfas/analytes.py:138` | lab table in code | `QC_LABEL_TO_CODE = {v: k for k, v in QC_TYPE_CODES.items()}` |
| `src/senaite/pfas/analytes.py:143` | lab table in code | `_QC_PRIORITY = [` |
| `src/senaite/pfas/egad_builder.py:39` | lab table in code | `_NC_FLAG_KEYWORDS = frozenset([` |
| `src/senaite/pfas/egad_builder.py:62` | lab table in code | `_LAB_REQUIRED = frozenset([` |
| `src/senaite/pfas/egad_builder.py:71` | lab table in code | `_QC_REQUIRED = frozenset([` |
| `src/senaite/pfas/egad_store.py:40` | lab table in code | `DEFAULT_LAB = {` |
| `src/senaite/pfas/egad_store.py:53` | lab table in code | `DEFAULT_METHOD_EGAD = {` |
| `src/senaite/pfas/egad_store.py:182` | lab table in code | `_DEFAULT_MATRIX_MAP = {` |
| `src/senaite/pfas/egad_store.py:390` | lab table in code | `DEFAULT_QUALIFIER_MAP = [` |
| `src/senaite/pfas/egad_store.py:414` | lab table in code | `DEFAULT_QC_TYPE_MAP = [` |
| `src/senaite/pfas/facility_qc.py:64` | lab table in code | `BALANCE_DEFAULTS = {` |
| `src/senaite/pfas/facility_qc.py:83` | lab table in code | `WATER_QC_DEFAULTS = {` |
| `src/senaite/pfas/holding_time.py:53` | lab table in code | `BLOCKING = frozenset([EXCEEDED, INVALID])` |
| `src/senaite/pfas/instrument_columns.py:99` | lab table in code | `NATIVE_COLUMN_MAP = {` |
| `src/senaite/pfas/method_baselines.py:115` | lab table in code | `_EIS_AQUEOUS = {` |
| `src/senaite/pfas/method_baselines.py:146` | lab table in code | `_EIS_MATRIX_OVERRIDES = {` |
| `src/senaite/pfas/method_baselines.py:266` | lab table in code | `_REGISTRY = {` |
| `src/senaite/pfas/method_profile_store.py:142` | lab table in code | `_FDA_MATRIX_EXCLUSIONS = {` |
| `src/senaite/pfas/method_profile_store.py:149` | lab table in code | `_EPA537_MATRICES = ["Drinking Water", "Groundwater", "Surface Water"]` |
| `src/senaite/pfas/method_profile_store.py:152` | lab table in code | `_EPA537_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:167` | lab table in code | `_EPA1633A_MATRICES = [` |
| `src/senaite/pfas/method_profile_store.py:172` | lab table in code | `_EPA1633A_UNIT_MAP = {` |
| `src/senaite/pfas/method_profile_store.py:186` | lab table in code | `_EPA1633A_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:230` | lab table in code | `DEFAULT_PROFILES = {` |
| `src/senaite/pfas/print_settings.py:23` | lab table in code | `DEFAULTS = {` |
| `src/senaite/pfas/qc_qualification.py:118` | lab table in code | `CONTROL_ROLES = frozenset([` |
| `src/senaite/pfas/qc_qualification.py:132` | lab table in code | `FAILURE_TYPES = [` |
| `src/senaite/pfas/qc_qualification.py:180` | lab table in code | `DEFAULT_LIBRARY = {` |
| `src/senaite/pfas/qc_qualification.py:311` | lab table in code | `_SOURCE_HINTS = [` |
| `src/senaite/pfas/ruleset.py:110` | lab table in code | `SHAPES_BY_KEY = {` |
| `src/senaite/pfas/ruleset.py:171` | lab table in code | `ANALYTE_SCOPED_KEYS = frozenset(["eis_recovery"])` |
| `src/senaite/pfas/ruleset.py:224` | lab table in code | `_LAB_EXTRACTORS = {` |
| `src/senaite/pfas/run_composition.py:101` | lab table in code | `_QC_ROLE_CODES = frozenset([` |
| `src/senaite/pfas/qc/qc_types.py:27` | lab table in code | `_ALIASES = {` |
| `src/senaite/pfas/qc/rules.py:40` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/qc/rules.py:45` | lab table in code | `METHODS = [{"id": mid, "label": _METHOD_SHORT_LABELS.get(mid, mid)}` |
| `src/senaite/pfas/qc/rules.py:52` | lab table in code | `RULE_LIBRARY = [` |
| `src/senaite/pfas/qc/rules.py:98` | lab table in code | `DEFAULT_METHOD_RULE_TOGGLES = {` |
| `src/senaite/pfas/qc/rules.py:127` | lab table in code | `DEFAULT_METHOD_OVERRIDES = {` |
| `src/senaite/pfas/qc/rules.py:137` | lab table in code | `LIBRARY_KEY_TO_ENGINE_CHECKS = {` |
| `src/senaite/pfas/qc/rules.py:152` | lab table in code | `DEFAULT_RULES = {` |
| `src/senaite/pfas/qc/store.py:47` | lab table in code | `_SCHEMA_STMTS = [` |
| `src/senaite/pfas/qc/store.py:172` | lab table in code | `_MIGRATION_STMTS = [` |
| `src/senaite/pfas/content/reagent.py:34` | lab table in code | `REAGENT_CATEGORIES = [` |
| `src/senaite/pfas/browser/controlchart.py:39` | lab table in code | `QC_TYPE_TARGETS = {` |
| `src/senaite/pfas/browser/controlchart.py:54` | lab table in code | `QC_TYPE_UNITS = {` |
| `src/senaite/pfas/browser/deviations.py:32` | lab table in code | `LIKELIHOOD_LABELS = {` |
| `src/senaite/pfas/browser/deviations.py:40` | lab table in code | `SEVERITY_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:51` | lab table in code | `_METHOD_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:90` | lab table in code | `_NEEDS_MANUAL_CAS = frozenset(["PFUnDS"])` |
| `src/senaite/pfas/browser/egad_publish.py:48` | agency / matrix code inlined | `def get_ar_sample_type(ar_obj, default="GW"):` |
| `src/senaite/pfas/browser/import_studio.py:210` | lab table in code | `_FALLBACK_PATTERNS = [` |
| `src/senaite/pfas/browser/label_print.py:35` | lab table in code | `LABEL_SIZES = [` |
| `src/senaite/pfas/browser/method_profiles.py:368` | lab table in code | `EIS_MATRIX_CLASSES = [` |
| `src/senaite/pfas/browser/method_wizard.py:45` | lab table in code | `STEP_META = [` |
| `src/senaite/pfas/browser/prep_logbooks.py:251` | lab table in code | `_BUILTIN_DEFS = [` |
| `src/senaite/pfas/browser/projects.py:51` | lab table in code | `ALL_STATUSES = [` |
| `src/senaite/pfas/browser/projects.py:72` | lab table in code | `CRITERIA_DEFS = [` |
| `src/senaite/pfas/browser/qc_grid.py:44` | lab table in code | `_DEFAULT_TIERS = {` |
| `src/senaite/pfas/browser/qc_grid.py:60` | lab table in code | `SPIKE_LEVELS = ["Low", "Mid", "High"]` |
| `src/senaite/pfas/browser/qc_grid.py:67` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/qcrules.py:23` | lab table in code | `GLOBAL_PARAM_META = {` |
| `src/senaite/pfas/browser/qcrules.py:40` | lab table in code | `QC_TYPE_FIELD_META = {` |
| `src/senaite/pfas/browser/reagents.py:71` | lab table in code | `EXPIRY_DEFAULTS = {` |
| `src/senaite/pfas/browser/setuprefs.py:43` | lab table in code | `QC_REF_SPEC = {` |
| `src/senaite/pfas/browser/setuprefs.py:363` | acceptance value inlined as a fallback | `lo = qt.get("recovery_min", 40.0)` |
| `src/senaite/pfas/browser/setuprefs.py:364` | acceptance value inlined as a fallback | `hi = qt.get("recovery_max", 140.0)` |
| `src/senaite/pfas/browser/sop_documents.py:35` | lab table in code | `_METHOD_ID_TO_SLUG = {` |
| `src/senaite/pfas/browser/sop_documents.py:40` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/sop_documents.py:78` | lab table in code | `DOC_TYPES = [` |
| `src/senaite/pfas/browser/system_map.py:41` | lab table in code | `NODES = [` |
| `src/senaite/pfas/migrations/migrate_profile_structure.py:44` | lab table in code | `OLD_KEYS = frozenset([` |

NO PRODUCER (0) — read off a profile, written by nothing
  none
