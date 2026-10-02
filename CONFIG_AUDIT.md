# Configurability audit

`tools/audit_configurable.py` · 118 profile keys examined

## Dead config (0)

The UI writes it; no engine code reads it. Editing it changes nothing.

None.

## Unreachable config (39)

The engine reads it; no UI writes it. The lab cannot change it.

| key | evidence |
|---|---|
| `associated_qc_types` | `src/senaite/pfas/qc/qc_types.py:75` |
| `eis_matrix_overrides` | `pfas_pipeline/method_profiles.py:1205`<br>`src/senaite/pfas/method_profile_sections.py:528`<br>`src/senaite/pfas/method_profile_sections.py:552` |
| `eis_overrides` | `pfas_pipeline/method_profiles.py:236`<br>`pfas_pipeline/method_profiles.py:1204`<br>`pfas_pipeline/method_profiles.py:1546` |
| `holding_times` | `src/senaite/pfas/holding_time.py:102`<br>`src/senaite/pfas/method_profile_sections.py:267` |
| `holding_times.Drinking Water` | `src/senaite/pfas/regulatory_limits.py:79`<br>`src/senaite/pfas/regulatory_limits.py:81`<br>`src/senaite/pfas/regulatory_limits.py:83` |
| `instrument_verification.calibration` | `pfas_pipeline/constants.py:103`<br>`src/senaite/pfas/browser/calibrations.py:142`<br>`src/senaite/pfas/browser/qc_review_report.py:179` |
| `instrument_verification.calibration.force_origin` | `pfas_pipeline/method_profiles.py:796`<br>`pfas_pipeline/method_profiles.py:910` |
| `instrument_verification.calibration.low_point_pct_dev_max` | `pfas_pipeline/method_profiles.py:795` |
| `instrument_verification.calibration.point_pct_dev_max` | `pfas_pipeline/constants.py:106`<br>`pfas_pipeline/constants.py:108`<br>`pfas_pipeline/method_profiles.py:794` |
| `instrument_verification.ccv` | `pfas_pipeline/method_profiles.py:658`<br>`pfas_pipeline/method_profiles.py:802`<br>`pfas_pipeline/method_profiles.py:840` |
| `instrument_verification.ccv.frequency` | `pfas_pipeline/method_profiles.py:659`<br>`pfas_pipeline/method_profiles.py:844`<br>`pfas_pipeline/method_profiles.py:943` |
| `instrument_verification.ccv.low_level_max` | `pfas_pipeline/method_profiles.py:1112` |
| `instrument_verification.ccv.low_level_min` | `pfas_pipeline/method_profiles.py:1111` |
| `instrument_verification.confirmation` | `pfas_pipeline/constants.py:116`<br>`src/senaite/pfas/browser/qc_review_report.py:182` |
| `instrument_verification.confirmation.ion_ratio_tol_pct` | `pfas_pipeline/constants.py:120`<br>`pfas_pipeline/qc_engine.py:352`<br>`pfas_pipeline/qc_engine.py:354` |
| `instrument_verification.confirmation.rrt_tol_pct` | `pfas_pipeline/constants.py:124` |
| `instrument_verification.confirmation.rt_tol_abs_min` | `pfas_pipeline/constants.py:122`<br>`pfas_pipeline/constants.py:123`<br>`pfas_pipeline/method_profiles.py:826` |
| `instrument_verification.confirmation.sn_confirm_min` | `pfas_pipeline/constants.py:144`<br>`pfas_pipeline/constants.py:145`<br>`pfas_pipeline/qc_engine.py:559` |
| `instrument_verification.confirmation.sn_quan_min` | `pfas_pipeline/constants.py:141`<br>`pfas_pipeline/constants.py:142`<br>`pfas_pipeline/constants.py:143` |
| `instrument_verification.is_response.vs_ical_avg_max` | `pfas_pipeline/constants.py:111`<br>`pfas_pipeline/constants.py:113`<br>`src/senaite/pfas/browser/qc_review_report.py:197` |
| `instrument_verification.is_response.vs_ical_avg_min` | `pfas_pipeline/constants.py:111`<br>`src/senaite/pfas/browser/qc_review_report.py:196` |
| `instrument_verification.is_response.vs_last_ccv_max` | `pfas_pipeline/method_profiles.py:812` |
| `instrument_verification.is_response.vs_last_ccv_min` | `pfas_pipeline/method_profiles.py:811` |
| `isomer_summation` | `pfas_pipeline/method_profiles.py:1626` |
| `isomer_summation[].branched` | `pfas_pipeline/method_profiles.py:1620`<br>`pfas_pipeline/method_profiles.py:1632`<br>`pfas_pipeline/pipeline.py:366` |
| `isomer_summation[].linear` | `pfas_pipeline/method_profiles.py:1621`<br>`pfas_pipeline/method_profiles.py:1623`<br>`pfas_pipeline/method_profiles.py:1765` |
| `isomer_summation[].reported` | `pfas_pipeline/method_profiles.py:1762`<br>`pfas_pipeline/pipeline.py:338`<br>`pfas_pipeline/pipeline.py:363` |
| `matrix_aliases` | `pfas_pipeline/method_profiles.py:576`<br>`src/senaite/pfas/method_profile_sections.py:265`<br>`src/senaite/pfas/report_limits.py:53` |
| `matrix_factors` | `pfas_pipeline/method_profiles.py:853`<br>`src/senaite/pfas/calibration_levels.py:116`<br>`src/senaite/pfas/method_profile_sections.py:316` |
| `salt_adjustment_factors` | `pfas_pipeline/method_profiles.py:1730`<br>`src/senaite/pfas/method_profile_sections.py:384`<br>`src/senaite/pfas/method_profile_sections.py:435` |
| `salt_adjustment_factors[].factor` | `pfas_pipeline/method_profiles.py:856`<br>`pfas_pipeline/method_profiles.py:860`<br>`pfas_pipeline/method_profiles.py:1743` |
| `salt_adjustment_factors[].lot_uid` | `src/senaite/pfas/method_profile_sections.py:387`<br>`src/senaite/pfas/method_profile_sections.py:428` |
| `spec_overrides` | `src/senaite/pfas/qc_consolidation.py:46` |
| `supported_matrices` | `src/senaite/pfas/matrix_ref.py:125`<br>`src/senaite/pfas/method_profile_sections.py:138`<br>`src/senaite/pfas/method_profile_sections.py:272` |
| `surrogate_is` | `pfas_pipeline/method_profiles.py:1485`<br>`pfas_pipeline/method_profiles.py:1493`<br>`pfas_pipeline/method_profiles.py:1666` |
| `surrogate_is_chain` | `pfas_pipeline/method_profiles.py:1711`<br>`src/senaite/pfas/labelled_standards.py:42` |
| `surrogate_map` | `pfas_pipeline/method_profiles.py:1484`<br>`pfas_pipeline/method_profiles.py:1490`<br>`pfas_pipeline/method_profiles.py:1652` |
| `tight_matrices` | `pfas_pipeline/method_profiles.py:579`<br>`src/senaite/pfas/method_profile_sections.py:334`<br>`src/senaite/pfas/method_profile_sections.py:1108` |
| `unit_map` | `pfas_pipeline/method_profiles.py:646`<br>`pfas_pipeline/method_profiles.py:1399`<br>`src/senaite/pfas/calibration_levels.py:138` |

## UI-only config (3)

An editor writes it and reads it back; nothing downstream consumes it. Looks alive, changes nothing.

| key | evidence |
|---|---|
| `run_template` | `src/senaite/pfas/browser/run_builder.py:261` |
| `run_template.bracket_qc` | `src/senaite/pfas/browser/run_builder.py:266`<br>`src/senaite/pfas/browser/run_builder.py:273`<br>`src/senaite/pfas/browser/run_builder.py:640` |
| `run_template.sequence` | `src/senaite/pfas/browser/run_builder.py:263`<br>`src/senaite/pfas/browser/run_builder.py:265`<br>`src/senaite/pfas/browser/run_builder.py:285` |

## Derived — not findings (3)

| key | derived by |
|---|---|
| `display_analyte_set` | method_profile_store.py:1253 — from the master set |
| `master_analyte_set` | method_profile_store.py:1239 — from the Method's services |
| `matrix_uid_map` | method_profile_store.py:1117 — from the Sample Type UIDs |

## Split keys (0)

None.

## Hardcoded lab values (121)

| location | kind | line |
|---|---|---|
| `pfas_pipeline/constants.py:50` | lab table in code | `_DEFAULT_CRITERIA = {` |
| `pfas_pipeline/constants.py:200` | lab table in code | `CRITERIA_METHOD = [None]` |
| `pfas_pipeline/method_profiles.py:154` | lab table in code | `_FDA_IS_DISPLAY_NAMES = [` |
| `pfas_pipeline/method_profiles.py:286` | lab table in code | `_OVERLAY_PATHS = {` |
| `pfas_pipeline/method_profiles.py:320` | lab table in code | `_CRITERIA_KEYS_BY_OVERLAY_KEY = {` |
| `pfas_pipeline/method_profiles.py:831` | acceptance value inlined as a fallback | `confirm_pct_diff_max=conf.get("confirm_pct_diff_max", 20.0),` |
| `pfas_pipeline/method_profiles.py:957` | acceptance value inlined as a fallback | `fallbacks of the form tier.get("recovery_min", 40.0), so a profile that was` |
| `pfas_pipeline/method_profiles.py:970` | lab table in code | `_TIER_STRUCTURAL_KEYS = frozenset([` |
| `pfas_pipeline/method_profiles.py:1338` | lab table in code | `_PROFILES = {` |
| `pfas_pipeline/method_profiles.py:1345` | lab table in code | `_ALIASES = {` |
| `pfas_pipeline/models.py:340` | lab table in code | `BATCH_QC_REQUIREMENTS = [` |
| `pfas_pipeline/qc_engine.py:859` | lab table in code | `NON_COUNTING = {"CAL", "CCV", "ICV", "CCB"}` |
| `pfas_pipeline/run_queue.py:1044` | lab table in code | `_CHECK_KINDS = {` |
| `pfas_pipeline/vendor_profiles.py:25` | lab table in code | `WATERS_MASSLYNX = {` |
| `pfas_pipeline/vendor_profiles.py:55` | lab table in code | `AGILENT_MASSHUNTER = {` |
| `pfas_pipeline/vendor_profiles.py:86` | lab table in code | `SCIEX_OS = {` |
| `src/senaite/pfas/analyte_reference.py:31` | lab table in code | `NATIVE_ANALYTES = [` |
| `src/senaite/pfas/analyte_reference.py:118` | lab table in code | `METHODS = [` |
| `src/senaite/pfas/analyte_reference.py:129` | lab table in code | `SAMPLE_TYPES = [` |
| `src/senaite/pfas/analyte_reference.py:148` | lab table in code | `CONTAINERS = [` |
| `src/senaite/pfas/analyte_reference.py:167` | lab table in code | `STORAGE_LOCATIONS = [` |
| `src/senaite/pfas/analyte_reference.py:179` | lab table in code | `PRESERVATIONS = [` |
| `src/senaite/pfas/analytes.py:12` | lab table in code | `PFAS_ANALYTES = [` |
| `src/senaite/pfas/analytes.py:58` | lab table in code | `IS_MRM = {` |
| `src/senaite/pfas/analytes.py:85` | lab table in code | `INJECTION_PATTERNS = [` |
| `src/senaite/pfas/analytes.py:100` | lab table in code | `QC_TYPE_CODES = {` |
| `src/senaite/pfas/analytes.py:115` | lab table in code | `QC_LABEL_TO_CODE = {v: k for k, v in QC_TYPE_CODES.items()}` |
| `src/senaite/pfas/analytes.py:120` | lab table in code | `_QC_PRIORITY = [` |
| `src/senaite/pfas/bench_queue.py:115` | lab table in code | `_STOP = frozenset([u"grade", u"lc", u"ms", u"lcms", u"hplc", u"the", u"and", u"in",` |
| `src/senaite/pfas/calibration_levels.py:30` | lab table in code | `PPT_PER_UNIT = {"ng/l": 1.0, "ng/kg": 1.0, "pg/g": 1.0, "pg/ml": 1.0,` |
| `src/senaite/pfas/calibration_levels.py:41` | lab table in code | `SEEDS = {` |
| `src/senaite/pfas/egad_format.py:29` | lab table in code | `_LAB_REQUIRED = frozenset([` |
| `src/senaite/pfas/egad_format.py:38` | lab table in code | `_QC_REQUIRED = frozenset([` |
| `src/senaite/pfas/egad_store.py:40` | lab table in code | `DEFAULT_LAB = {` |
| `src/senaite/pfas/egad_store.py:53` | lab table in code | `DEFAULT_METHOD_EGAD = {` |
| `src/senaite/pfas/egad_store.py:204` | lab table in code | `_DEFAULT_MATRIX_MAP = {` |
| `src/senaite/pfas/egad_store.py:417` | lab table in code | `DEFAULT_QUALIFIER_MAP = [` |
| `src/senaite/pfas/egad_store.py:441` | lab table in code | `DEFAULT_QC_TYPE_MAP = [` |
| `src/senaite/pfas/facility_qc.py:64` | lab table in code | `BALANCE_DEFAULTS = {` |
| `src/senaite/pfas/facility_qc.py:83` | lab table in code | `WATER_QC_DEFAULTS = {` |
| `src/senaite/pfas/holding_time.py:53` | lab table in code | `BLOCKING = frozenset([EXCEEDED, INVALID])` |
| `src/senaite/pfas/instrument_columns.py:99` | lab table in code | `NATIVE_COLUMN_MAP = {` |
| `src/senaite/pfas/inventory_ledger.py:38` | lab table in code | `_COUNT = frozenset([u"ea", u"each", u"pc", u"pcs", u"piece", u"pieces", u"unit", u"units",` |
| `src/senaite/pfas/low_level_tiers.py:31` | lab table in code | `SEEDS_537_1 = {` |
| `src/senaite/pfas/low_level_tiers.py:49` | lab table in code | `_FIRST_SEED = ["LFB", "LFSM", "LFSMD"]          # what a "2026-10-01" marker covered` |
| `src/senaite/pfas/method_baselines.py:115` | lab table in code | `_EIS_AQUEOUS = {` |
| `src/senaite/pfas/method_baselines.py:146` | lab table in code | `_EIS_MATRIX_OVERRIDES = {` |
| `src/senaite/pfas/method_baselines.py:266` | lab table in code | `_REGISTRY = {` |
| `src/senaite/pfas/method_profile_sections.py:253` | lab table in code | `COMMON_UNITS = [u"ng/kg", u"ug/kg", u"ng/L", u"ng/mL", u"ug/L", u"mg/kg", u"pg/g"]` |
| `src/senaite/pfas/method_profile_sections.py:514` | lab table in code | `EIS_MATRIX_CLASSES = [(u"solid", u"Solid (soil, sediment)"), (u"biosolid", u"Biosolid"),` |
| `src/senaite/pfas/method_profile_sections.py:818` | lab table in code | `SPIKE_LABELS = {u"LFSM": u"LFSM / LFSMD", u"LFB": u"LFB", u"LCS": u"LCS"}` |
| `src/senaite/pfas/method_profile_sections.py:870` | lab table in code | `GROUP_CHOICES = [(u"all", u"All analytes"), (u"key", u"Key analytes"),` |
| `src/senaite/pfas/method_profile_sections.py:872` | lab table in code | `SCOPE_CHOICES = [(u"all", u"All matrices"), (u"tight", u"Tier 1 matrices only")]` |
| `src/senaite/pfas/method_profile_sections.py:955` | lab table in code | `_TIER_HEAD = [cf.Field("name", u"Tier", kind=cf.TEXT, placeholder=u"new tier"),` |
| `src/senaite/pfas/method_profile_sections.py:1293` | lab table in code | `QC_KIND = {"MB": "blank", "LRB": "blank", "MXB": "blank",` |
| `src/senaite/pfas/method_profile_sections.py:1299` | lab table in code | `PROFILE_KEY = {"DUP": "Dup", "MXB": "MxB"}` |
| `src/senaite/pfas/method_profile_sections.py:1300` | lab table in code | `CONFIGURED_ON = {"instrument": ("pane-cal", u"Calibration & CCV"),` |
| `src/senaite/pfas/method_profile_sections.py:1347` | lab table in code | `PROFILE_CHECKS = [((u"sur", u"ls"), check_profile), ((u"iso",), check_isomers)]` |
| `src/senaite/pfas/method_profile_store.py:138` | lab table in code | `_FDA_MATRIX_EXCLUSIONS = {` |
| `src/senaite/pfas/method_profile_store.py:145` | lab table in code | `_EPA537_MATRICES = ["Drinking Water", "Groundwater", "Surface Water"]` |
| `src/senaite/pfas/method_profile_store.py:148` | lab table in code | `_EPA537_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:163` | lab table in code | `_EPA1633A_MATRICES = [` |
| `src/senaite/pfas/method_profile_store.py:168` | lab table in code | `_EPA1633A_UNIT_MAP = {` |
| `src/senaite/pfas/method_profile_store.py:182` | lab table in code | `_EPA1633A_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:226` | lab table in code | `DEFAULT_PROFILES = {` |
| `src/senaite/pfas/print_settings.py:28` | lab table in code | `DEFAULTS = {` |
| `src/senaite/pfas/project_specs.py:390` | lab table in code | `_INSTRUMENT_CHECKS = [` |
| `src/senaite/pfas/qc_qualification.py:118` | lab table in code | `CONTROL_ROLES = frozenset([` |
| `src/senaite/pfas/qc_qualification.py:132` | lab table in code | `FAILURE_TYPES = [` |
| `src/senaite/pfas/qc_qualification.py:180` | lab table in code | `DEFAULT_LIBRARY = {` |
| `src/senaite/pfas/qc_qualification.py:316` | lab table in code | `_SOURCE_HINTS = [` |
| `src/senaite/pfas/qc_schema.py:23` | lab table in code | `TABLES = [` |
| `src/senaite/pfas/qc_schema.py:163` | lab table in code | `MIGRATIONS = [` |
| `src/senaite/pfas/regulatory_limits.py:40` | lab table in code | `_UNITS = {` |
| `src/senaite/pfas/regulatory_limits.py:78` | lab table in code | `SEED_LIMITS = [` |
| `src/senaite/pfas/report_format.py:26` | lab table in code | `YES_NO = [("yes", "Show"), ("no", "Hide")]` |
| `src/senaite/pfas/report_format.py:29` | lab table in code | `SETTINGS = [` |
| `src/senaite/pfas/ruleset.py:109` | lab table in code | `SHAPES_BY_KEY = {` |
| `src/senaite/pfas/ruleset.py:170` | lab table in code | `ANALYTE_SCOPED_KEYS = frozenset(["eis_recovery"])` |
| `src/senaite/pfas/ruleset.py:223` | lab table in code | `_LAB_EXTRACTORS = {` |
| `src/senaite/pfas/run_composition.py:101` | lab table in code | `_QC_ROLE_CODES = frozenset([` |
| `src/senaite/pfas/sample_correction.py:28` | lab table in code | `_PER_GRAM = {u"ng/g": 1.0, u"ug/kg": 1.0, u"µg/kg": 1.0, u"ng/kg": 1000.0,` |
| `src/senaite/pfas/sample_correction.py:30` | lab table in code | `_PER_ML = {u"ng/ml": 1.0, u"ug/l": 1.0, u"µg/l": 1.0, u"ng/l": 1000.0, u"pg/ml": 1000.0}` |
| `src/senaite/pfas/settings_report.py:31` | lab table in code | `QC_APPLICATION = [` |
| `src/senaite/pfas/settings_report.py:62` | lab table in code | `INSTRUMENT_APPLICATION = [` |
| `src/senaite/pfas/settings_report.py:84` | lab table in code | `CONSUMED_TOGGLES = frozenset(["is_response", "rrt_deviation", "ion_ratio", "cal_r2",` |
| `src/senaite/pfas/qc/qc_types.py:27` | lab table in code | `_ALIASES = {` |
| `src/senaite/pfas/qc/rules.py:40` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/qc/rules.py:45` | lab table in code | `METHODS = [{"id": mid, "label": _METHOD_SHORT_LABELS.get(mid, mid)}` |
| `src/senaite/pfas/qc/rules.py:55` | lab table in code | `RULE_LIBRARY = [` |
| `src/senaite/pfas/qc/rules.py:98` | lab table in code | `DEFAULT_METHOD_RULE_TOGGLES = {` |
| `src/senaite/pfas/qc/rules.py:131` | lab table in code | `QC_TYPE_SWITCHES = [` |
| `src/senaite/pfas/qc/rules.py:197` | lab table in code | `LIBRARY_KEY_TO_ENGINE_CHECKS = {` |
| `src/senaite/pfas/qc/rules.py:213` | lab table in code | `DEFAULT_RULES = {` |
| `src/senaite/pfas/browser/bench_inventory.py:36` | lab table in code | `KIND_LABELS = {REAGENT: u"Reagent", PREPARED: u"Prepared standard"}` |
| `src/senaite/pfas/browser/controlchart.py:39` | lab table in code | `QC_TYPE_TARGETS = {` |
| `src/senaite/pfas/browser/controlchart.py:54` | lab table in code | `QC_TYPE_UNITS = {` |
| `src/senaite/pfas/browser/deviations.py:33` | lab table in code | `LIKELIHOOD_LABELS = {` |
| `src/senaite/pfas/browser/deviations.py:41` | lab table in code | `SEVERITY_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:50` | lab table in code | `_METHOD_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:89` | lab table in code | `_NEEDS_MANUAL_CAS = frozenset(["PFUnDS"])` |
| `src/senaite/pfas/browser/egad_publish.py:48` | agency / matrix code inlined | `def get_ar_sample_type(ar_obj, default="GW"):` |
| `src/senaite/pfas/browser/facility_qc.py:93` | lab table in code | `UNITS_GATES = {` |
| `src/senaite/pfas/browser/import_studio.py:211` | lab table in code | `_FALLBACK_PATTERNS = [` |
| `src/senaite/pfas/browser/label_print.py:35` | lab table in code | `LABEL_SIZES = [` |
| `src/senaite/pfas/browser/method_wizard.py:45` | lab table in code | `STEP_META = [` |
| `src/senaite/pfas/browser/perms.py:53` | lab table in code | `_TIER_ROLES = {` |
| `src/senaite/pfas/browser/prep_logbooks.py:267` | lab table in code | `_BUILTIN_DEFS = [` |
| `src/senaite/pfas/browser/project_specs_view.py:30` | lab table in code | `TABS = [("an", u"Analytes & limits", ("px", "rl")),` |
| `src/senaite/pfas/browser/projects.py:50` | lab table in code | `ALL_STATUSES = [` |
| `src/senaite/pfas/browser/qc_grid.py:44` | lab table in code | `SPIKE_LEVELS = ["Low", "Mid", "High"]` |
| `src/senaite/pfas/browser/qc_grid.py:51` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/reagents.py:72` | lab table in code | `EXPIRY_DEFAULTS = {` |
| `src/senaite/pfas/browser/reagents.py:689` | lab table in code | `REAGENT_GATES = {` |
| `src/senaite/pfas/browser/regulatory_limits_view.py:26` | lab table in code | `REGULATORY_GATES = {"save": TIER_CONFIG}` |
| `src/senaite/pfas/browser/setuprefs.py:44` | lab table in code | `QC_REF_SPEC = {` |
| `src/senaite/pfas/browser/sop_documents.py:35` | lab table in code | `_METHOD_ID_TO_SLUG = {` |
| `src/senaite/pfas/browser/sop_documents.py:40` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/sop_documents.py:78` | lab table in code | `DOC_TYPES = [` |
| `src/senaite/pfas/browser/system_map.py:41` | lab table in code | `NODES = [` |
| `src/senaite/pfas/migrations/migrate_profile_structure.py:44` | lab table in code | `OLD_KEYS = frozenset([` |

NO PRODUCER (5) — read off a profile, written by nothing
  isomers
      read at pfas_pipeline/method_profiles.py:1614
  key_analytes
      read at src/senaite/pfas/method_profile_store.py:992
  labelled_standards
      read at pfas_pipeline/method_profiles.py:1707
      read at pfas_pipeline/method_profiles.py:1479
  reporting_limits
      read at pfas_pipeline/method_profiles.py:645
  sample_correction
      read at pfas_pipeline/method_profiles.py:1391
