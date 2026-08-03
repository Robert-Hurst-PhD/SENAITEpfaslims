# Configurability audit

`tools/audit_configurable.py` · 109 profile keys examined

## Dead config (1)

The UI writes it; no engine code reads it. Editing it changes nothing.

| key | evidence |
|---|---|
| `surrogate_is_chain` | `src/senaite/pfas/method_profile_store.py:366` |

## Unreachable config (7)

The engine reads it; no UI writes it. The lab cannot change it.

| key | evidence |
|---|---|
| `eis_matrix_overrides` | `pfas_pipeline/method_profiles.py:797` |
| `extraction_corrections.salt_factors` | `src/senaite/pfas/browser/qcrules.py:165` |
| `matrix_aliases` | `pfas_pipeline/method_profiles.py:426` |
| `spec_overrides` | `src/senaite/pfas/spec_reverse.py:10`<br>`src/senaite/pfas/spec_reverse.py:138`<br>`src/senaite/pfas/spec_sync.py:179` |
| `supported_matrices` | `src/senaite/pfas/matrix_ref.py:125`<br>`src/senaite/pfas/method_profile_store.py:108`<br>`src/senaite/pfas/method_profile_store.py:109` |
| `tight_matrices` | `pfas_pipeline/method_profiles.py:429`<br>`pfas_pipeline/method_profiles.py:483`<br>`src/senaite/pfas/spec_sync.py:148` |
| `unit_map` | `pfas_pipeline/method_profiles.py:943`<br>`src/senaite/pfas/browser/qc_review_report.py:150` |

## Derived — not findings (3)

| key | derived by |
|---|---|
| `display_analyte_set` | method_profile_store.py:1253 — from the master set |
| `master_analyte_set` | method_profile_store.py:1239 — from the Method's services |
| `matrix_uid_map` | method_profile_store.py:1117 — from the Sample Type UIDs |

## Split keys (0)

None.

## Hardcoded lab values (144)

| location | kind | line |
|---|---|---|
| `pfas_pipeline/barcode.py:28` | lab table in code | `DEFAULT_SHELF_LIFE_DAYS = {` |
| `pfas_pipeline/constants.py:49` | lab table in code | `_DEFAULT_CRITERIA = {` |
| `pfas_pipeline/egad_edd.py:94` | lab table in code | `_LAB_REQUIRED = frozenset([` |
| `pfas_pipeline/egad_edd.py:103` | lab table in code | `_QC_REQUIRED = frozenset([` |
| `pfas_pipeline/egad_edd.py:114` | lab table in code | `DEFAULT_QUALIFIER_MAP = {` |
| `pfas_pipeline/egad_edd.py:129` | lab table in code | `DEFAULT_QC_TYPE_MAP = {` |
| `pfas_pipeline/egad_edd.py:152` | lab table in code | `METHOD_TEST_CODES = {` |
| `pfas_pipeline/injection_builder.py:23` | lab table in code | `FDA_CAL_LEVELS = [` |
| `pfas_pipeline/injection_builder.py:39` | lab table in code | `EPA537_CAL_LEVELS = [` |
| `pfas_pipeline/injection_builder.py:48` | lab table in code | `EPA537_QCS = [("537-QCS-1", "80/320 ppt"), ("537-QCS-2", "20/80 ppt")]` |
| `pfas_pipeline/method_profiles.py:162` | lab table in code | `_DEFAULT_PROFILE_CACHE = {` |
| `pfas_pipeline/method_profiles.py:443` | acceptance value inlined as a fallback | `tier.get("recovery_min", 40.0),` |
| `pfas_pipeline/method_profiles.py:444` | acceptance value inlined as a fallback | `tier.get("recovery_max", 140.0),` |
| `pfas_pipeline/method_profiles.py:445` | acceptance value inlined as a fallback | `rsd_max=tier.get("rsd_max", 30.0),` |
| `pfas_pipeline/method_profiles.py:451` | acceptance value inlined as a fallback | `tier.get("recovery_min", 80.0),` |
| `pfas_pipeline/method_profiles.py:452` | acceptance value inlined as a fallback | `tier.get("recovery_max", 120.0),` |
| `pfas_pipeline/method_profiles.py:453` | acceptance value inlined as a fallback | `rsd_max=tier.get("rsd_max", 20.0),` |
| `pfas_pipeline/method_profiles.py:462` | acceptance value inlined as a fallback | `tier.get("recovery_min", 65.0),` |
| `pfas_pipeline/method_profiles.py:463` | acceptance value inlined as a fallback | `tier.get("recovery_max", 135.0),` |
| `pfas_pipeline/method_profiles.py:464` | acceptance value inlined as a fallback | `rsd_max=tier.get("rsd_max", 25.0),` |
| `pfas_pipeline/method_profiles.py:493` | acceptance value inlined as a fallback | `return QCRule(t3.get("recovery_min", 40.0), t3.get("recovery_max", 140.0),` |
| `pfas_pipeline/method_profiles.py:494` | acceptance value inlined as a fallback | `rsd_max=t3.get("rsd_max", 30.0),` |
| `pfas_pipeline/method_profiles.py:497` | acceptance value inlined as a fallback | `return QCRule(t1.get("recovery_min", 80.0), t1.get("recovery_max", 120.0),` |
| `pfas_pipeline/method_profiles.py:498` | acceptance value inlined as a fallback | `rsd_max=t1.get("rsd_max", 20.0),` |
| `pfas_pipeline/method_profiles.py:500` | acceptance value inlined as a fallback | `return QCRule(t2.get("recovery_min", 65.0), t2.get("recovery_max", 135.0),` |
| `pfas_pipeline/method_profiles.py:501` | acceptance value inlined as a fallback | `rsd_max=t2.get("rsd_max", 25.0),` |
| `pfas_pipeline/method_profiles.py:619` | acceptance value inlined as a fallback | `r2_min=float(cal.get("r2_min", 0.990)),` |
| `pfas_pipeline/method_profiles.py:630` | acceptance value inlined as a fallback | `recovery_min=float(ccv.get("recovery_min", 70.0)),` |
| `pfas_pipeline/method_profiles.py:631` | acceptance value inlined as a fallback | `recovery_max=float(ccv.get("recovery_max", 130.0)),` |
| `pfas_pipeline/method_profiles.py:640` | acceptance value inlined as a fallback | `vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),` |
| `pfas_pipeline/method_profiles.py:641` | acceptance value inlined as a fallback | `vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),` |
| `pfas_pipeline/method_profiles.py:650` | acceptance value inlined as a fallback | `ion_ratio_tol_pct=conf.get("ion_ratio_tol_pct", 30.0),` |
| `pfas_pipeline/method_profiles.py:651` | acceptance value inlined as a fallback | `rrt_tol_pct=conf.get("rrt_tol_pct", 1.0),` |
| `pfas_pipeline/method_profiles.py:653` | acceptance value inlined as a fallback | `sn_min_quant=conf.get("sn_quan_min", 3.0),` |
| `pfas_pipeline/method_profiles.py:654` | acceptance value inlined as a fallback | `sn_min_confirm=conf.get("sn_confirm_min", 3.0),` |
| `pfas_pipeline/method_profiles.py:711` | acceptance value inlined as a fallback | `lo = float(t.get("recovery_min", 70.0))` |
| `pfas_pipeline/method_profiles.py:712` | acceptance value inlined as a fallback | `hi = float(t.get("recovery_max", 130.0))` |
| `pfas_pipeline/method_profiles.py:726` | acceptance value inlined as a fallback | `r2_min=float(cal.get("r2_min", 0.990)),` |
| `pfas_pipeline/method_profiles.py:727` | acceptance value inlined as a fallback | `point_pct_dev_max=cal.get("point_pct_dev_max", 30.0),` |
| `pfas_pipeline/method_profiles.py:728` | acceptance value inlined as a fallback | `low_point_pct_dev_max=cal.get("low_point_pct_dev_max", 50.0),` |
| `pfas_pipeline/method_profiles.py:735` | acceptance value inlined as a fallback | `recovery_min=float(ccv.get("recovery_min", 70.0)),` |
| `pfas_pipeline/method_profiles.py:736` | acceptance value inlined as a fallback | `recovery_max=float(ccv.get("recovery_max", 130.0)),` |
| `pfas_pipeline/method_profiles.py:738` | acceptance value inlined as a fallback | `low_level_min=ccv.get("low_level_min", 50.0),` |
| `pfas_pipeline/method_profiles.py:739` | acceptance value inlined as a fallback | `low_level_max=ccv.get("low_level_max", 150.0),` |
| `pfas_pipeline/method_profiles.py:745` | acceptance value inlined as a fallback | `vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),` |
| `pfas_pipeline/method_profiles.py:746` | acceptance value inlined as a fallback | `vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),` |
| `pfas_pipeline/method_profiles.py:747` | acceptance value inlined as a fallback | `vs_last_ccv_min=is_.get("vs_last_ccv_min", 70.0),` |
| `pfas_pipeline/method_profiles.py:748` | acceptance value inlined as a fallback | `vs_last_ccv_max=is_.get("vs_last_ccv_max", 140.0),` |
| `pfas_pipeline/method_profiles.py:756` | acceptance value inlined as a fallback | `rt_tol_abs_min=conf.get("rt_tol_abs_min", 0.05),` |
| `pfas_pipeline/method_profiles.py:804` | acceptance value inlined as a fallback | `default_lo = float(t.get("recovery_min", 40.0))` |
| `pfas_pipeline/method_profiles.py:805` | acceptance value inlined as a fallback | `default_hi = float(t.get("recovery_max", 130.0))` |
| `pfas_pipeline/method_profiles.py:845` | acceptance value inlined as a fallback | `r2_min=float(cal.get("r2_min", 0.990)),` |
| `pfas_pipeline/method_profiles.py:846` | acceptance value inlined as a fallback | `point_pct_dev_max=cal.get("point_pct_dev_max", 30.0),` |
| `pfas_pipeline/method_profiles.py:847` | acceptance value inlined as a fallback | `low_point_pct_dev_max=cal.get("low_point_pct_dev_max", 50.0),` |
| `pfas_pipeline/method_profiles.py:855` | acceptance value inlined as a fallback | `recovery_min=float(ccv.get("recovery_min", 70.0)),` |
| `pfas_pipeline/method_profiles.py:856` | acceptance value inlined as a fallback | `recovery_max=float(ccv.get("recovery_max", 130.0)),` |
| `pfas_pipeline/method_profiles.py:863` | acceptance value inlined as a fallback | `vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),` |
| `pfas_pipeline/method_profiles.py:864` | acceptance value inlined as a fallback | `vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),` |
| `pfas_pipeline/method_profiles.py:871` | acceptance value inlined as a fallback | `ion_ratio_tol_pct=conf.get("ion_ratio_tol_pct", 50.0),` |
| `pfas_pipeline/method_profiles.py:872` | acceptance value inlined as a fallback | `sn_min_quant=conf.get("sn_quan_min", 3.0),` |
| `pfas_pipeline/method_profiles.py:873` | acceptance value inlined as a fallback | `sn_min_confirm=conf.get("sn_confirm_min", 1.0),` |
| `pfas_pipeline/method_profiles.py:891` | lab table in code | `_PROFILES = {` |
| `pfas_pipeline/method_profiles.py:898` | lab table in code | `_ALIASES = {` |
| `pfas_pipeline/models.py:312` | lab table in code | `BATCH_QC_REQUIREMENTS = [` |
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
| `src/senaite/pfas/egad_store.py:159` | lab table in code | `_DEFAULT_MATRIX_MAP = {` |
| `src/senaite/pfas/egad_store.py:367` | lab table in code | `DEFAULT_QUALIFIER_MAP = [` |
| `src/senaite/pfas/egad_store.py:384` | lab table in code | `DEFAULT_QC_TYPE_MAP = [` |
| `src/senaite/pfas/facility_qc.py:32` | lab table in code | `UNIT_TYPES = [` |
| `src/senaite/pfas/facility_qc.py:43` | lab table in code | `BALANCE_DEFAULTS = {` |
| `src/senaite/pfas/facility_qc.py:62` | lab table in code | `WATER_QC_DEFAULTS = {` |
| `src/senaite/pfas/facility_qc.py:261` | acceptance value inlined as a fallback | `_f(data.get("study_tolerance", 1.0)),` |
| `src/senaite/pfas/facility_qc.py:279` | acceptance value inlined as a fallback | `_f(data.get("study_tolerance", 1.0)),` |
| `src/senaite/pfas/facility_qc.py:451` | acceptance value inlined as a fallback | `tol = float(p.get("tolerance_g", 0.001))` |
| `src/senaite/pfas/instrument_columns.py:99` | lab table in code | `NATIVE_COLUMN_MAP = {` |
| `src/senaite/pfas/method_profile_store.py:141` | lab table in code | `_FDA_MATRIX_EXCLUSIONS = {` |
| `src/senaite/pfas/method_profile_store.py:148` | lab table in code | `_EPA537_MATRICES = ["Drinking Water", "Groundwater", "Surface Water"]` |
| `src/senaite/pfas/method_profile_store.py:151` | lab table in code | `_EPA537_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:166` | lab table in code | `_EPA1633A_MATRICES = [` |
| `src/senaite/pfas/method_profile_store.py:171` | lab table in code | `_EPA1633A_UNIT_MAP = {` |
| `src/senaite/pfas/method_profile_store.py:185` | lab table in code | `_EPA1633A_ANALYTE_KEYWORDS = [` |
| `src/senaite/pfas/method_profile_store.py:229` | lab table in code | `DEFAULT_PROFILES = {` |
| `src/senaite/pfas/print_settings.py:23` | lab table in code | `DEFAULTS = {` |
| `src/senaite/pfas/qc/qc_types.py:27` | lab table in code | `_ALIASES = {` |
| `src/senaite/pfas/qc/rules.py:40` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/qc/rules.py:45` | lab table in code | `METHODS = [{"id": mid, "label": _METHOD_SHORT_LABELS.get(mid, mid)}` |
| `src/senaite/pfas/qc/rules.py:52` | lab table in code | `RULE_LIBRARY = [` |
| `src/senaite/pfas/qc/rules.py:86` | lab table in code | `DEFAULT_METHOD_RULE_TOGGLES = {` |
| `src/senaite/pfas/qc/rules.py:107` | lab table in code | `DEFAULT_METHOD_OVERRIDES = {` |
| `src/senaite/pfas/qc/rules.py:117` | lab table in code | `LIBRARY_KEY_TO_ENGINE_CHECKS = {` |
| `src/senaite/pfas/qc/rules.py:131` | lab table in code | `DEFAULT_RULES = {` |
| `src/senaite/pfas/qc/store.py:47` | lab table in code | `_SCHEMA_STMTS = [` |
| `src/senaite/pfas/qc/store.py:172` | lab table in code | `_MIGRATION_STMTS = [` |
| `src/senaite/pfas/content/reagent.py:23` | lab table in code | `REAGENT_CATEGORIES = [` |
| `src/senaite/pfas/browser/controlchart.py:39` | lab table in code | `QC_TYPE_TARGETS = {` |
| `src/senaite/pfas/browser/controlchart.py:54` | lab table in code | `QC_TYPE_UNITS = {` |
| `src/senaite/pfas/browser/data_review.py:175` | lab table in code | `_MSG_TEXTS = {` |
| `src/senaite/pfas/browser/deviations.py:28` | lab table in code | `LIKELIHOOD_LABELS = {` |
| `src/senaite/pfas/browser/deviations.py:36` | lab table in code | `SEVERITY_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:51` | lab table in code | `_METHOD_LABELS = {` |
| `src/senaite/pfas/browser/egad_config.py:90` | lab table in code | `_NEEDS_MANUAL_CAS = frozenset(["PFUnDS"])` |
| `src/senaite/pfas/browser/egad_publish.py:48` | agency / matrix code inlined | `def get_ar_sample_type(ar_obj, default="GW"):` |
| `src/senaite/pfas/browser/import_studio.py:210` | lab table in code | `_FALLBACK_PATTERNS = [` |
| `src/senaite/pfas/browser/label_print.py:35` | lab table in code | `LABEL_SIZES = [` |
| `src/senaite/pfas/browser/method_profiles.py:229` | acceptance value inlined as a fallback | `return self.profile().get("duplicate", {}).get("rpd_max", 20.0)` |
| `src/senaite/pfas/browser/method_wizard.py:43` | lab table in code | `STEP_META = [` |
| `src/senaite/pfas/browser/prep_logbooks.py:251` | lab table in code | `_BUILTIN_DEFS = [` |
| `src/senaite/pfas/browser/qc_grid.py:44` | lab table in code | `_DEFAULT_TIERS = {` |
| `src/senaite/pfas/browser/qc_grid.py:60` | lab table in code | `SPIKE_LEVELS = ["Low", "Mid", "High"]` |
| `src/senaite/pfas/browser/qc_grid.py:67` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/qcrules.py:23` | lab table in code | `GLOBAL_PARAM_META = {` |
| `src/senaite/pfas/browser/qcrules.py:40` | lab table in code | `QC_TYPE_FIELD_META = {` |
| `src/senaite/pfas/browser/qcrules.py:176` | acceptance value inlined as a fallback | `"default":   mdict.get("default", 1.0),` |
| `src/senaite/pfas/browser/reagents.py:71` | lab table in code | `EXPIRY_DEFAULTS = {` |
| `src/senaite/pfas/browser/setuprefs.py:43` | lab table in code | `QC_REF_SPEC = {` |
| `src/senaite/pfas/browser/setuprefs.py:188` | acceptance value inlined as a fallback | `lo = qt.get("recovery_min", 40.0)` |
| `src/senaite/pfas/browser/setuprefs.py:189` | acceptance value inlined as a fallback | `hi = qt.get("recovery_max", 140.0)` |
| `src/senaite/pfas/browser/setuprefs.py:259` | acceptance value inlined as a fallback | `lo = qt.get("recovery_min", 40.0)` |
| `src/senaite/pfas/browser/setuprefs.py:260` | acceptance value inlined as a fallback | `hi = qt.get("recovery_max", 140.0)` |
| `src/senaite/pfas/browser/sop_documents.py:34` | lab table in code | `_METHOD_ID_TO_SLUG = {` |
| `src/senaite/pfas/browser/sop_documents.py:39` | lab table in code | `_METHOD_SHORT_LABELS = {` |
| `src/senaite/pfas/browser/system_map.py:41` | lab table in code | `NODES = [` |
| `src/senaite/pfas/migrations/migrate_profile_structure.py:32` | lab table in code | `OLD_KEYS = frozenset([` |
