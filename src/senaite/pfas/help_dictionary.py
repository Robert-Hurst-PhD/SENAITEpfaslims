# -*- coding: utf-8 -*-
"""The central Help dictionary (@@pfas-help).

One entry per CONCEPT, fixed in the system:

    id, term, group, text     what it is, in a few sentences
    where   [(button label, portal-relative path)]   where it is set
    who     a permission tier of browser/perms ("config", "site_admin"),
            "bench" (bench and review roles), or "system" (derived; nobody
            edits it directly)
    effects [(what it changes, file, marker)]  what it affects downstream.
            Every claim names the code that delivers it; tests/test_help_
            dictionary.py checks the marker is in that file, so a claim
            cannot outlive the code (as the settings report's claims are
            pinned).
    lists   names of generated lists (help_lists in the view): read from
            the system's own registries, never typed here.

Pages carry one line of purpose and a "?" button per concept that opens its
entry (pfas_macros "help"). Regulatory sources are named as the methods
name them, never by internal tracking numbers.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# The Help page's tabs, in the order the lab works ("a tabbed
# help page with a structure"), each with the one line it shows.
GROUPS = (
    "Method setup",
    "QC criteria",
    "Bench and extraction",
    "Instrument runs",
    "Review and release",
    "Reporting",
    "EDD",
    "Signatures and access",
)
GROUP_INTROS = {
    "Method setup": "What a method is: its analytes per matrix, standards, factors and limits.",
    "QC criteria": "What each QC must meet, and how a failure is qualified or blocks release.",
    "Bench and extraction": "The extraction batch, its records and the equipment behind them.",
    "Instrument runs": "Calibration, the injection list, the import and corrections to a run.",
    "Review and release": "The technical review before a result is released.",
    "Reporting": "How a result is stated on the certificate and which documents are issued.",
    "EDD": "The electronic data deliverable a state receives.",
    "Signatures and access": "Who may sign, approve and sign in where.",
}

# The overview tab: the lab's order of work, each step naming the entries
# behind it (ids below).
WORKFLOW = [
    ("Set up the method", "Analytes per matrix, standards, factors and QC.",
     ("method-profile", "analyte-matrix", "qc-types")),
    ("Register and receive samples", "Holding times start at collection; a project can change the method's settings.",
     ("holding-time", "project-specs")),
    ("Build the extraction batch", "Samples, the QC the method asks for, each QC's parent and level, then labels.",
     ("extraction-batch", "spike-levels")),
    ("Extract", "The guided extraction records every lot, amount and deviation.",
     ("guided-extraction", "traceability", "logbooks")),
    ("Run the instrument", "A new curve or not, the injection list, the import.",
     ("calibration-decision", "sequence-export", "import-profiles")),
    ("Review", "QC, manual integrations, dilutions and re-injections, then the five checks.",
     ("data-review", "manual-integration", "dilution")),
    ("Report", "Rounding, the reporting template and what holds a certificate.",
     ("rounding", "reporting-template", "publishing-holds")),
    ("Deliver", "The state's electronic data deliverable.",
     ("edd-profiles", "edd-qualifiers")),
]

# Which tab each entry is on.
_TAB = {
    "Method setup": ("method-profile", "analyte-matrix", "labelled-standards", "isomers", "salt-factor",
                     "matrix-factor", "calibration-levels", "holding-time", "project-specs", "config-history"),
    "QC criteria": ("qc-types", "spike-levels", "recovery-tiers", "eis-limits", "rule-switches",
                    "specifications", "qualified-release", "judged-value", "method-studies"),
    "Bench and extraction": ("extraction-batch", "guided-extraction", "traceability", "dilution", "logbooks",
                             "equipment-types", "balance-before-weighing", "homogenisation", "coc",
                             "temperature-study", "expiry-defaults"),
    "Instrument runs": ("calibration-decision", "ccv-bracketing", "sequence-export", "import-profiles",
                        "manual-integration", "identity-confirmation", "reprocess"),
    "Review and release": ("data-review", "qc-standards-table", "publishing-holds", "method-identified"),
    "Reporting": ("rounding", "rl", "non-detect", "reporting-format", "action-level", "reporting-template",
                  "document-designs", "settings-report"),
    "EDD": ("edd-values", "edd-qualifiers", "edd-profiles"),
    "Signatures and access": ("sign-rights", "lab-director", "badges"),
}
TAB_OF = dict((eid, tab) for tab, ids in _TAB.items() for eid in ids)

P = "src/senaite/pfas/"
W = "pfas_pipeline/"

ENTRIES = [
    # ── Method studies ────────────────────────────
    {"id": "method-studies", "term": "Method studies (MDL, MRL, precision and accuracy, DL)",
     "text": "A study is calculated from results the runs already stored, for one method "
             "and matrix. Annual MDL: 40 CFR 136 Appendix B Revision 2 -- the greater of "
             "MDLs (spiked LFBs at one spiking level) and MDLb (method blanks), over the "
             "last 24 months. MRL confirmation: seven LFBs at the proposed MRL, upper "
             "prediction limit at most 150 %, lower at least 50 % (EPA 537.1 9.2.6). "
             "Precision and accuracy: four to seven mid-level LFBs, RSD under 20 %, mean "
             "recovery within 30 % (9.2.3, 9.2.4). Detection limit: seven or more LFBs over "
             "three days (9.2.8). A result is excluded only with a reason. QA approval "
             "freezes the study, writes its MDLs (or a confirmed MRL as the RL) to the "
             "method's Reporting Limits and freezes the packet PDF.",
     "where": [("Method Studies", "@@pfas-method-studies")],
     "who": "config",
     "effects": [
         ("MDL per Appendix B Revision 2", P + "method_studies.py", "def mdl_rev2"),
         ("MRL prediction interval", P + "method_studies.py", "HR_PIR_7 = 3.963"),
         ("An exclusion needs a reason", P + "study_records.py", "Say why the result is excluded."),
         ("Approval writes Reporting Limits", P + "browser/method_studies.py", "sr.apply_to_profile("),
     ]},
    # ── Results and reporting ─────────────────────────────────────────────
    {"id": "rounding", "term": "Rounding rule and significant figures",
     "text": "How every reported number is rounded, set per method and matrix on the "
             "method's Reporting tab: EPA and FDA round half up, ISO rounds half to "
             "even. Results, reporting limits (RL) and MDLs share the significant "
             "figures; QC percentages are whole percents.",
     "where": [("Reporting tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Certificate results, RL and MDL", P + "coa_format.py", "_rounding.round_sig"),
         ("EDD values (the certificate's own rows)", P + "edd_builder.py", "self._certificate_rows(ar)"),
         ("The QC checks of the pipeline judge the rounded value", W + "qc_engine.py", "profile.judged_pct("),
         ("Each run records the rule it was judged with", W + "injection_store.py", "judged_rule"),
     ]},
    {"id": "judged-value", "term": "Judged on the rounded value",
     "text": "Every result and QC check compares the value as the report states it: a "
             "concentration at the reported significant figures, a recovery, RPD or "
             "response as a whole percent. Criteria (RL, MDL, windows, MCLs) are used "
             "as configured. Instrument criteria (retention time, ion ratio, S/N, r²) "
             "are not rounded.",
     "where": [("Reporting tab", "@@pfas-method-profiles")],
     "who": "system",
     "effects": [
         ("Detected versus the RL (U qualifier)", P + "coa_format.py", "judged < rl"),
         ("Recovery and RPD windows", W + "qc_engine.py", "judged = profile.judged_pct(recovery_pct, matrix)"),
         ("Method blank, MDL and duplicate detection", W + "run_queue.py", "profile.judged_conc("),
         ("A run judged under another rule is held", P + "coa_qc_standards.py", "\"rule_changed\""),
     ]},
    {"id": "rl", "term": "Reporting limit (RL)",
     "text": "The lowest concentration reported as a number; below it a result is a "
             "non-detect. It is the RL typed on the method's Reporting Limits tab, else "
             "the method's lowest calibration level in the reporting unit. A diluted "
             "result's RL is multiplied by the dilution.",
     "where": [("Reporting Limits tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Derived from the lowest calibrator when none is typed", P + "calibration_levels.py", "def derived_rl"),
         ("Scaled by the dilution", P + "report_limits.py", "def scaled_rl"),
         ("Printed on the certificate and the EDD", P + "coa_format.py", "\"rl\": format_rl(rl, n, rule)"),
     ]},
    {"id": "non-detect", "term": "Non-detect (U)",
     "text": "A result below the RL. The certificate prints it as \"< RL\", \"ND\" or as "
             "stored (Reporting tab) with the qualifier U; the EDD leaves the "
             "concentration blank and issues the state's code for it.",
     "where": [("Reporting tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Certificate wording", P + "coa_format.py", "def format_result"),
         ("EDD concentration and qualifier", P + "edd_builder.py", "codes = [\"N.D.\"]"),
     ]},
    {"id": "reporting-format", "term": "Certificate format (Reporting tab)",
     "text": "The certificate settings per method and matrix: which columns show, how "
             "non-detects print, significant figures, rounding rule and the notes. A "
             "matrix row inherits blank cells from \"All matrices\". Certificates use "
             "these settings as they were when the reporting template was issued.",
     "where": [("Reporting tab", "@@pfas-method-profiles"), ("Reporting Template", "@@pfas-report-template")],
     "who": "config",
     "lists": ["report_format_settings"],
     "effects": [
         ("Read from the issued reporting-template revision", P + "browser/coa_sections.py", "snap, _rev = self.template_revision()"),
         ("Handed to the pipeline from the issued revision", P + "method_profile_store.py", "report_format_rev"),
     ]},
    {"id": "action-level", "term": "MCL / action level (regulatory limit)",
     "text": "A limit from a regulatory program (e.g. the US EPA PFAS MCLs). Kept on "
             "Regulatory Limits with its citation; a limit reaches a certificate only "
             "once the laboratory marks it Verified. A limit on several analytes is "
             "compared with the sum of their reported values.",
     "where": [("Regulatory Limits", "@@pfas-regulatory-limits"), ("Reporting tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Only verified limits apply", P + "regulatory_limits.py", "if l.get(\"verified\")"),
         ("Compared with the certificate's rounded values", P + "browser/coa_sections.py", "by_kw = dict((r[\"keyword\"], r) for r in rows)"),
     ]},
    {"id": "qc-standards-table", "term": "Surrogate and internal-standard table",
     "text": "The certificate's quality control sub-table for the sample's neat "
             "injection: a surrogate's % recovery or an internal standard's response "
             "as % of the calibration average, the window, and the status the "
             "pipeline decided. \"No criterion set\" is never a pass.",
     "where": [("Reporting tab (note)", "@@pfas-method-profiles")],
     "who": "system",
     "lists": ["qc_statuses"],
     "effects": [
         ("Rows from the stored verdicts, neat injection only", P + "coa_qc_standards.py", "def select(rows, client_sid)"),
         ("Required on a designed certificate", P + "coa_document.py", "\"qc_standards\": _qcs.REQUIRED"),
     ]},
    # ── Quality control ───────────────────────────────────────────────────
    {"id": "method-profile", "term": "Method profile",
     "text": "Everything a method is judged by, in one place: its analytes and "
             "matrices, recovery tiers, internal standards, calibration and CCV "
             "criteria, reporting limits and certificate format. The pipeline and the "
             "certificate read it; nothing keeps a second copy.",
     "where": [("Method Profiles", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Exported to the pipeline on every save", P + "method_profile_store.py", "def export_profiles_to_file"),
     ]},
    {"id": "recovery-tiers", "term": "Recovery tiers",
     "text": "The recovery windows per QC type, by analyte group (key analytes, "
             "analytes with their own labelled standard, analytes without one) and, "
             "for FDA, by matrix. A low-level tier applies only to spikes at or below "
             "a set multiple of the RL.",
     "where": [("Recovery Tiers tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Judged by the pipeline per analyte and matrix", W + "qc_engine.py", "def recovery_check_profiled"),
         ("Low-level tier needs the spike level and the RL", W + "method_profiles.py", "LOW_LEVEL_KEY = \"low_level_x_rl\""),
     ]},
    {"id": "rule-switches", "term": "QC rule switches",
     "text": "Which checks the pipeline runs for a method. A switched-off check is not "
             "evaluated at all; its limits stay on the method's tabs.",
     "where": [("Rule Toggles tab", "@@pfas-method-profiles")],
     "who": "config",
     "lists": ["rule_switches"],
     "effects": [
         ("Read by the pipeline before each check", W + "run_queue.py", "_rule_enabled(toggles,"),
     ]},
    {"id": "qualified-release", "term": "QC qualification codes",
     "text": "When a QC criterion fails on client material, the reviewer may release "
             "the result qualified: it carries a code and the certificate states what "
             "it means. A failure on laboratory control material (blank, calibration, "
             "CCV) blocks instead.",
     "where": [("Data Review", "@@pfas-data-review")],
     "who": "bench",
     "lists": ["qualification_codes"],
     "effects": [
         ("Codes and default dispositions", P + "qc_qualification.py", "FAILURE_TYPES = ["),
         ("Issued in the EDD as the state's codes", P + "edd_builder.py", "def _issue_qualifiers"),
     ]},
    {"id": "manual-integration", "term": "Manual integration",
     "text": "Setting a peak's baseline by hand when the software integrated it wrongly. "
             "Each one is identified from the instrument export (the column mapped to "
             "Manual Changes, read with the import profile's markers) or from the "
             "report, justified with a reason, signed by the analyst and then a "
             "different reviewer, and its before and after pages are stamped. Every page "
             "of the report carrying the lab's heading (found by scanning the report on "
             "upload) must be listed or dismissed with a reason, countersigned. Never to make QC pass (VELAP Manual Integration TAD, Virginia "
             "DCLS 2016).",
     "where": [("Import Studio", "@@pfas-import-studio"), ("Data Review", "@@pfas-data-review"),
               ("Reasons", "@@pfas-mi-reasons")],
     "who": "bench",
     "effects": [
         ("Blocks the Instrument Report gate until complete", P + "browser/data_review.py", "if not self.mi_gate()[0]:"),
         ("Reviewer must not be the analyst; an edit clears signatures", P + "manual_integration.py", "the reviewer must not be the analyst"),
         ("The stamp never covers the report", "tools/pdfme/server.mjs", "page.translateContent(0, strip);"),
         ("Every heading page listed or dismissed", P + "manual_integration.py", "carries the heading but is not listed"),
         ("Every uploaded report is scanned for heading pages", P + "browser/data_review.py", "_miv.scan_quietly(filepath)"),
         ("A report not yet scanned is refused", P + "browser/manual_integration_view.py", "ok, need = False, [NOT_SCANNED] + need"),
         ("Dismissals and 'none' are countersigned", P + "manual_integration.py", "the reviewer must not be the person who made it"),
         ("A second upload never moves the pages to another file", P + "browser/manual_integration_view.py", "if pinned in names:"),
         ("Decided once, with the import profile's markers", W + "importer.py", "_mi.is_manual(r.get(\"manual_changes\"), _mi_markers)"),
         ("Stored per result", W + "injection_store.py", "manual_raw,manual_integration"),
     ]},
    {"id": "identity-confirmation", "term": "Identity confirmation (single transition)",
     "text": "FDA C-010.04 §10.2(4): PFBA and PFPeA have one usable MS/MS transition, "
             "so a positive must be confirmed by a second, independent technique "
             "agreeing within the method's % difference. The reviewer is asked; an "
             "unconfirmed result is released with the CONF qualifier.",
     "where": [("Calibration & CCV tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Prompted for a detected PFBA / PFPeA", W + "qc_engine.py", "def single_transition_confirm_needed"),
     ]},
    {"id": "holding-time", "term": "Holding time",
     "text": "The time allowed between collection and extraction, set per method. A "
             "sample past it fails the Chain of Custody gate of Data Review whatever "
             "the checkbox says.",
     "where": [("Lab Workflow tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Computed for the Chain of Custody gate", P + "browser/data_review.py", "def holding_time_summary"),
     ]},
    {"id": "specifications", "term": "Specifications",
     "text": "The recovery windows each method (or a project's batches) is judged "
             "against. They are part of the method profile (Recovery Tiers); a project's "
             "Specs change them for its batches. SENAITE's own Analysis Specifications "
             "are not used, because they would judge a concentration against a recovery "
             "window.",
     "where": [("Recovery Tiers tab", "@@pfas-method-profiles"), ("Projects", "@@pfas-projects")],
     "who": "system",
     "effects": [
         ("A project's batches run to its effective profile", P + "project_specs.py", "def effective_for_project("),
     ]},
    {"id": "analyte-matrix", "term": "Analyte \u00d7 matrix",
     "text": "Which of the method's analytes are reported in which matrix. An unticked "
             "analyte is left out for that matrix everywhere: QC checks, certificates "
             "and the EDD.",
     "where": [("Analyte \u00d7 Matrix tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read by the pipeline per matrix", W + "method_profiles.py", "inclusion = data.get(\"analyte_matrix_inclusion\")"),
     ]},
    {"id": "labelled-standards", "term": "Labelled standards",
     "text": "Every isotopically labelled standard the method uses, its role (extracted "
             "surrogate or injection internal standard) and the native analytes linked "
             "to it. An analyte linked to its own labelled analogue has its own "
             "labelled standard; the others fall in the \"no labelled standard\" tier.",
     "where": [("Internal Standards tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Decides the \"no labelled standard\" analytes", P + "method_profile_sections.py", "def no_std_set"),
         ("Surrogate versus internal-standard checks", W + "qc_engine.py", "get_labelled_roles(method_id)"),
     ]},
    {"id": "isomers", "term": "Isomers (linear and branched)",
     "text": "An analyte measured as separate linear and branched peaks is reported as "
             "one summed result under its reported name; the peaks are summed before the "
             "salt and matrix factors. The individual peaks stay visible only for the "
             "laboratory's own review (control charts, retention time, calibration).",
     "where": [("Isomers tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Peaks summed by the pipeline", W + "pipeline.py", "def _sum_isomer_pair"),
         ("Reported name on every page and the certificate", P + "isomers.py", "def label(profile, keyword, titles)"),
     ]},
    {"id": "salt-factor", "term": "Salt factor",
     "text": "The molar-mass correction for a standard supplied as a salt: molar mass of "
             "the free acid divided by that of the salt (1.0 = none). Each is tied to "
             "the reference-standard lot (CoA) it comes from.",
     "where": [("Sample Corrections tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Applied by the pipeline per analyte", W + "pipeline.py", "salt_factors = _get_salt_factors(method_id)"),
     ]},
    {"id": "matrix-factor", "term": "Matrix factor and sample correction",
     "text": "How a concentration in the extract becomes one in the sample: reported = "
             "instrument \u00d7 factor, one factor per matrix, or back-calculated from "
             "each sample's logged amount and extract volume. The RL derived from the "
             "calibration levels uses the same factor.",
     "where": [("Sample Corrections tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read by the pipeline per matrix", W + "method_profiles.py", "def get_matrix_factor"),
         ("The derived RL", P + "calibration_levels.py", "matrix_factors"),
     ]},
    {"id": "qc-types", "term": "QC types",
     "text": "The batch QC samples a method runs (method blank, LFB / LCS, LFSM, "
             "LFSMD, duplicate). A type switched on for the first time has no limits "
             "and is not judged until they are set.",
     "where": [("QC Types tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Which QC types the pipeline judges", P + "qc/qc_types.py", "def enabled_qc_types"),
     ]},
    {"id": "ccv-bracketing", "term": "CCV bracketing",
     "text": "A continuing calibration verification is run after every N counting "
             "injections (field samples and extraction QC; not calibrators or the ICV), "
             "and a closing CCV ends the run. N is the method's CCV frequency; the Run "
             "Builder inserts the CCVs.",
     "where": [("Calibration & CCV tab", "@@pfas-method-profiles"), ("Run Builder", "@@pfas-run-builder")],
     "who": "config",
     "effects": [
         ("Spacing checked by the pipeline", W + "qc_engine.py", "def ccv_frequency_check"),
     ]},
    {"id": "dilution", "term": "Dilutions",
     "text": "A sample that read above the calibration range is re-injected diluted. "
             "The dilution is logged as a total fold (e.g. 10); the diluted result is "
             "reported as a retest of the analysis, with its own time and an RL "
             "multiplied by the fold.",
     "where": [("Extraction Guide", "@@pfas-extraction-guide")],
     "who": "bench",
     "effects": [
         ("Reported as a SENAITE retest", P + "browser/dilution_retests.py", "from bika.lims.utils.analysis import create_retest"),
         ("RL scaled by the fold", P + "report_limits.py", "def scaled_rl"),
     ]},
    {"id": "data-review", "term": "Data Review gates",
     "text": "The technical review before release (ISO/IEC 17025 7.8.4): chain of "
             "custody, reagent and standard traceability, QC summary, final data and "
             "instrument report must all pass before the analyst submits and a manager "
             "verifies.",
     "where": [("Data Review", "@@pfas-data-review")],
     "who": "bench",
     "effects": [
         ("Review checks raised by the pipeline", W + "review_checks.py", "REVIEW_CHECKS"),
     ]},
    {"id": "spike-levels", "term": "Spike levels",
     "text": "The concentration a spiked QC sample is fortified at, per level (Low, "
             "Mid, High) and matrix, in that matrix's reporting unit (soil in ng/g, "
             "water in ng/L). Each spike in an extraction batch is given a level; its "
             "amount is the level's unless the bench records what was added. LFSMD "
             "uses its LFSM's. Without a level, recovery is not judged and the release "
             "is held.",
     "where": [("Recovery Tiers tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read for each spiked injection", W + "method_profiles.py", "def resolve_spike"),
     ]},
    {"id": "sequence-export", "term": "Injection list",
     "text": "The built run as the file the instrument software imports (Waters "
             "MassLynx), kept per instrument in Import Studio beside its import "
             "mapping. One column per line, HEADER = source: name (the injection "
             "name), description, vial, type, masslynx-type (Analyte / Standard / QC / "
             "Blank), level, or fixed:text for a constant such as the MS or inlet "
             "method file. Until an instrument has one saved, the MassLynx starter is "
             "used, named as such. The worksheet's Export button gives the same file.",
     "where": [("Import Studio", "@@pfas-import-studio"), ("Run Builder", "@@pfas-run-builder")],
     "who": "config",
     "effects": [
         ("Written to the injection list", P + "run_plan.py", "def export_rows"),
         ("Kept per instrument", P + "instrument_export.py", "def columns_for"),
     ]},
    {"id": "calibration-decision", "term": "New calibration curve",
     "text": "Whether a run carries a new calibration curve. The method profile says "
             "when one is needed (every run, or when the last curve is too old or not "
             "approved); otherwise the Run Builder asks the bench chemist. A run on a "
             "reused curve opens with a CCV (or an ICV, if the method says so); a new "
             "curve is followed by an ICV unless the method says not. The answer and "
             "who gave it are recorded on the run.",
     "where": [("Calibration & CCV tab", "@@pfas-method-profiles"), ("Run Builder", "@@pfas-run-builder")],
     "who": "bench",
     "effects": [
         ("Decided", P + "run_plan.py", "def curve_decision"),
         ("Opening checks", P + "run_plan.py", "def opening"),
     ]},
    {"id": "extraction-batch", "term": "Extraction batch",
     "text": "The worksheet is the extraction batch: its samples, then the QC the "
             "method profile (or the project plan) asks for, then each QC's parent "
             "sample and spike level, before labels are printed. Every member is "
             "injected under the name the LIMS gives it: a sample's SENAITE id, a QC "
             "'<worksheet>-<QC><n>'.",
     "where": [("Worksheet: Extraction batch", "@@pfas-extraction-batch")],
     "who": "bench",
     "effects": [
         ("QC populated from the method", P + "extraction_batch.py", "def plan_qc"),
         ("Read by the pipeline as the spike record", P + "dilution_ref.py", "extraction_batch.spike_map"),
     ]},
    {"id": "calibration-levels", "term": "Calibration levels",
     "text": "The method's calibration ladder, in ng/mL in the extract or ppt in the "
             "sample. Its lowest level gives each analyte's RL unless one is typed (an "
             "ng/mL level is multiplied by the matrix factor), and it suggests the spike "
             "levels. An analyte calibrated over another range has a multiple of the "
             "ladder up to its highest standard.",
     "where": [("Reporting Limits tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("The derived RL", P + "calibration_levels.py", "def derived_rl"),
     ]},
    {"id": "eis-limits", "term": "Surrogate (EIS) recovery limits",
     "text": "EPA 1633A only: the recovery window per labelled surrogate (SUR "
             "designation), for aqueous samples and per matrix class. A class limit "
             "overrides the aqueous one for that class; a blank class cell uses the "
             "aqueous limit.",
     "where": [("Internal Standards tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("One grid, stored per designation", P + "method_profile_sections.py", "def read_eis_grid"),
     ]},
    # ── Publishing and documents ──────────────────────────────────────────
    {"id": "reporting-template", "term": "Reporting template revision",
     "text": "The controlled version of the certificate: its layout, the per-method "
             "certificate formats and any designed layout, issued together by a "
             "manager. Nothing is published before the first revision; a later change "
             "shows as an unissued change until the next one is issued.",
     "where": [("Reporting Template", "@@pfas-report-template")],
     "who": "config",
     "effects": [
         ("Publishing waits for the first revision", P + "browser/guards.py", "class ReportTemplateGuard"),
         ("A designed certificate must be complete to issue", P + "browser/report_template.py", "dt.validate(\"coa\", designed)"),
     ]},
    {"id": "document-designs", "term": "Designed documents",
     "text": "Layouts drawn in the document designer for the certificate, extraction "
             "log, QC Review, settings report, logbooks and labels. A design is a "
             "draft until issued; an issued design is that document from then on, and "
             "it must show every required part.",
     "where": [("Document Templates", "@@pfas-document-templates")],
     "who": "config",
     "lists": ["doc_categories"],
     "effects": [
         ("Required parts checked when issuing", P + "document_templates.py", "def validate(kind, template)"),
     ]},
    {"id": "expiry-defaults", "term": "Expiry defaults",
     "text": "The shelf life given to a lot whose label states no expiry: a reagent from "
             "its receipt, a mobile phase and any other container from its opening, a "
             "prepared standard from its preparation. An in-house preparation also takes "
             "a parent lot's expiry when that is earlier than its own.",
     "where": [("Reagent Inventory", "@@pfas-reagents")],
     "who": "config",
     "effects": [
         ("A lot without a stated expiry", P + "browser/reagents.py", "reagent_default_days"),
         ("A preparation inherits an earlier parent expiry", P + "browser/prepared_standards.py",
          "expiry_inherited_from"),
     ]},
    {"id": "logbooks", "term": "Logbooks",
     "text": "Templates are the versioned logbook forms, numbered FM-ENV-001 onwards. A "
             "method's sequence says which templates its batches use, in order, and each "
             "batch's logbooks are filled in under By batch. A correction keeps the "
             "original value and records who changed it.",
     "where": [("Logbooks", "@@pfas-logbook-index")],
     "who": "config",
     "effects": [
         ("Form numbers from the logbook sequence", P + "logbook_store.py", "def form_code("),
     ]},
    {"id": "settings-report", "term": "Settings report",
     "text": "Every quality-control setting and whether the pipeline actually judges it, "
             "printable for an assessor. A blank setting is unset (the method default "
             "applies). The configuration id changes whenever any setting changes, so "
             "two reports with the same id describe the same configuration.",
     "where": [("Print on Method Profiles", "@@pfas-method-profiles")],
     "who": "system",
     "effects": [
         ("Configuration id over every store", P + "settings_report.py", "def fingerprint(*stores)"),
     ]},
    {"id": "publishing-holds", "term": "Why a sample cannot be published",
     "text": "Publishing (and re-publishing) is held until the cause is fixed: no "
             "identified method, no issued reporting template, or a run whose "
             "surrogate / internal-standard verdicts are missing, unrounded or judged "
             "under another rule. A sample with no run at all is not held.",
     "where": [("Data Review", "@@pfas-data-review"), ("Reporting Template", "@@pfas-report-template")],
     "who": "system",
     "lists": ["publish_holds"],
     "effects": [
         ("Method identified", P + "browser/guards.py", "class SampleMethodGuard"),
         ("Reporting template issued", P + "browser/guards.py", "class ReportTemplateGuard"),
         ("Surrogate / internal-standard verdicts", P + "browser/guards.py", "class QCStandardsGuard"),
     ]},
    {"id": "reprocess", "term": "Reprocess a run",
     "text": "Import the run's instrument file again so the pipeline re-judges it with "
             "today's method profile and issued rounding rule. Needed for runs stored "
             "before verdicts were kept or before checks used the rounded value.",
     "where": [("Run Builder", "@@pfas-run-builder")],
     "who": "bench",
     "effects": [
         ("A re-import replaces the run's stored rows", W + "injection_store.py", "DELETE FROM injection_results WHERE batch_id=?"),
     ]},
    {"id": "method-identified", "term": "Identified method",
     "text": "A certificate needs one method: the one every reported analysis carries "
             "(set when it goes on a worksheet with a method). An analyte a project "
             "adds to the method is accepted without it.",
     "where": [("Worksheets", "worksheets")],
     "who": "bench",
     "effects": [
         ("One answer for the certificate and the publish check", P + "sample_method.py", "def identify_from"),
         ("A project's added analytes accepted", P + "sample_method.py", "def project_added"),
     ]},
    # ── Signatures and access ─────────────────────────────────────────────
    {"id": "sign-rights", "term": "Sign rights",
     "text": "Who may sign as preparer, reviewer or Laboratory Director, set per person "
             "on Lab Staff with their title, credentials and signature. A designed "
             "document that places a signature its signer may not give is refused.",
     "where": [("Lab Staff", "@@pfas-lab-staff"), ("My profile", "@@pfas-my-profile")],
     "who": "config",
     "effects": [
         ("Certificate signatories checked", P + "browser/coa_document.py", "may not sign as"),
         ("Extraction log, QC Review and logbook signatories", P + "browser/doc_people.py", "class SignatoryError"),
     ]},
    {"id": "lab-director", "term": "Laboratory Director",
     "text": "The one person named in Site Settings whose name and signature appear as "
             "Director on designed documents.",
     "where": [("Site Settings", "@@pfas-site-settings")],
     "who": "config",
     "effects": [
         ("Read for every designed document", P + "browser/staff.py", "def director_userid"),
     ]},
    {"id": "badges", "term": "Badges and lab terminals",
     "text": "At a registered lab terminal a badge scan signs its holder in (and "
             "switches user); the terminal signs out after 10 minutes without "
             "activity. Administrators always use their password.",
     "where": [("Lab terminals", "@@pfas-terminals"), ("Lab Staff", "@@pfas-lab-staff")],
     "who": "config",
     "effects": [
         ("Idle sign-out enforced by the server", P + "browser/badges.py", "IDLE_SECONDS = 600"),
         ("No badge sign-in for administrators", P + "browser/badges.py", "NO_BADGE_ROLES"),
     ]},
    # ── EDD ───────────────────────────────────────────────────────────────
    {"id": "edd-values", "term": "EDD values and precision",
     "text": "The EDD reports exactly what the certificate reports: the rounded "
             "result, RL and MDL at the laboratory's precision, and the same "
             "non-detect decision. A sample the certificate cannot assemble blocks the "
             "EDD.",
     "where": [("EDD Export", "@@pfas-edd-config")],
     "who": "system",
     "effects": [
         ("Rows from the certificate's assembly", P + "edd_builder.py", "def _certificate_rows"),
     ]},
    {"id": "edd-qualifiers", "term": "EDD qualifier codes",
     "text": "Each internal qualifier on a result is issued as the state's code from "
             "the state profile's qualifier map, distinct codes joined. An internal "
             "code without a state code, or a joined code the state does not accept, "
             "blocks the EDD until it is mapped.",
     "where": [("EDD Export", "@@pfas-edd-config")],
     "who": "config",
     "effects": [
         ("Mapped, joined, unmapped refused", P + "edd_builder.py", "def _issue_qualifiers"),
     ]},
    {"id": "edd-profiles", "term": "EDD state profiles",
     "text": "Each state program's EDD format and vocabulary: columns and headings, "
             "sample-type codes, qualifier and QC-type codes, and the state's analyte "
             "codes. The seeded format is the base; a client is given a profile on its EDD "
             "page. The state's lookup tables keep the valid codes current.",
     "where": [("EDD Export", "@@pfas-edd-config")],
     "who": "config",
     "effects": [
         ("A client's profile (the default profile otherwise)", P + "edd_store.py", "def get_edd_profile_for_client"),
     ]},
    {"id": "import-profiles", "term": "Import profiles",
     "text": "How an instrument's export columns map to what the pipeline reads, saved "
             "per instrument and software version in Import Studio. A file without an "
             "active profile is refused, never guessed.",
     "where": [("Import Studio", "@@pfas-import-studio")],
     "who": "config",
     "effects": [
         ("The pipeline reads only saved mappings", W + "importer.py", "column mapping saved in Import Studio"),
     ]},
    # ── Projects ──────────────────────────────────────────────────────────
    {"id": "project-specs", "term": "Project specs",
     "text": "A project's differences from its method (added analytes, reporting "
             "limits, recovery windows, RPD limits, labelled standards). Batches linked "
             "to the project are judged and reported by the method with these applied "
             "(the effective profile). Anything looser than the method is listed as a "
             "departure on the certificate.",
     "where": [("Projects", "@@pfas-projects")],
     "who": "config",
     "effects": [
         ("Certificate and Data Review read the effective profile", P + "project_specs.py", "def profile_for_batch"),
         ("Departures from the method", P + "project_specs.py", "def departures"),
     ]},
    # ── Equipment and traceability ────────────────────────────────────────
    {"id": "equipment-types", "term": "Equipment type obligations",
     "text": "What every instrument of a type owes: how often it is checked, whether "
             "its readings are corrected, whether an external certificate is needed, "
             "its unit and tolerance. Set on the type, never per page.",
     "where": [("Equipment Types", "@@pfas-equipment-types")],
     "who": "config",
     "effects": [
         ("Due dates per type", P + "equipment_types.py", "def due(req,"),
         ("Balance tolerance as a percentage of nominal", P + "equipment_types.py", "def within(nominal, actual, pct)"),
     ]},
    {"id": "coc", "term": "Chain of custody",
     "text": "One CoC per shipment, numbered by the LIMS. The sampler enters each sample "
             "and submits; the laboratory records receipt, temperatures (judged against the "
             "method profile's range) and compliance. "
             "A paper kit CoC is transcribed here and its scan attached before receipt.",
     "where": [("Chain of Custody", "@@pfas-coc")],
     "who": "bench",
     "effects": [
         ("What blocks receipt, and what is flagged", P + "coc_records.py", "def receipt_problems(record, receipt, extra_flags=())"),
         ("Receipt temperatures judged against the method's range", P + "coc_records.py", "def judge_temperatures(readings, on_ice)"),
         ("Who may edit a CoC", P + "coc_records.py", "def may_edit(record, staff, own_client)"),
         ("What a CoC row must give", P + "coc_entry.py", "def row_problems(rows, field_qc_types)"),
     ]},
    {"id": "homogenisation", "term": "Homogenisation and composites",
     "text": "Each sample states how it is homogenised, prefilled from its matrix's default "
             "when it is made. A composite states how many units were combined and what. "
             "The bench records each homogenisation; what differs from the request needs a note.",
     "where": [("Homogenisation", "@@pfas-homogenisation"),
               ("Homogenisation Methods", "@@pfas-homogenisation-setup")],
     "who": "bench",
     "effects": [
         ("The matrix default is frozen on the new sample", P + "homogenisation.py", "def on_sample_initialized(sample, event)"),
         ("What a composite must state", P + "homogenisation.py", "def composite_problems(composite, units, description)"),
         ("What a homogenisation record must explain in a note", P + "homogenisation.py", "def record_warnings(req, method, unit_name, cleaned, units_combined, methods)"),
     ]},
    {"id": "balance-before-weighing", "term": "Balance verified before weighing",
     "text": "A stage that lists a balance cannot be completed until the balance chosen "
             "has passed its verification that day. A deviation note does not unlock it. "
             "A correction is judged on the day the stage was first done.",
     "where": [("Balance", "@@pfas-balance-log"), ("Extraction Guide", "@@pfas-extraction-guide")],
     "who": "bench",
     "effects": [
         ("Blank, unregistered, failed and unverified balances block", P + "bench_queue.py", "def balance_blocks(balances)"),
         ("The stage refuses whatever note is written", P + "browser/extraction_guide.py", "if blocks or (warnings and not deviations):"),
     ]},
    {"id": "guided-extraction", "term": "Guided extraction",
     "text": "The method's extraction stages, walked through step by step on a batch: "
             "every reagent, standard and consumable lot is picked from the inventory, "
             "sample amounts and dilutions are recorded, and the finished record is the "
             "batch's Extraction Log, handed to the pipeline with the run. The stage that "
             "takes the test portion is the Sample Processing Log.",
     "where": [("Lab Workflow tab", "@@pfas-method-profiles"), ("Extraction Guide", "@@pfas-extraction-guide")],
     "who": "bench",
     "effects": [
         ("Stages from the method profile", P + "browser/extraction_guide.py", "profile.get(\"extraction_stages\")"),
         ("The sample processing stage", P + "sample_table.py", "def processing_stage(stages)"),
         ("Checks a stage asks to be ticked", P + "extraction_review.py", "def unconfirmed(stage_def, ticked)"),
     ]},
    {"id": "temperature-study", "term": "Temperature correction study",
     "text": "Four paired readings over two days with the probe beside the "
             "NIST-traceable reference thermometer, every quarter and at installation. "
             "The correction (reference average minus probe average) is applied to the "
             "probe's readings until the next study, including receipt temperatures on "
             "the chain of custody. The reference thermometer itself is certified "
             "externally.",
     "where": [("Temperature Log", "@@pfas-temperature-log"), ("Equipment", "@@pfas-equipment")],
     "who": "bench",
     "effects": [
         ("Frozen onto the chain of custody at receipt", P + "receipt_temperature.py", "freeze(unit, correction, as_of)"),
         ("Quarterly study set on the type", P + "equipment_types.py", "NIST reference by a study every quarter"),
     ]},
    {"id": "config-history", "term": "Configuration history",
     "text": "Every save of laboratory configuration: who, when and each value before "
             "and after. A revert puts one change back through its own page and is "
             "itself recorded; it is refused if a later change touched the same "
             "settings.",
     "where": [("Configuration History", "@@pfas-config-history")],
     "who": "config",
     "effects": [
         ("Recorded on every tracked save", P + "config_history.py", "def track("),
     ]},
    {"id": "traceability", "term": "Reagent and standard traceability",
     "text": "Every result traces to the prepared standards used (calibration and "
             "extraction logs), each prepared standard to the reagent lots it was made "
             "from, and each reagent to its certificate. A lot named in a logbook but "
             "missing from the inventory fails Data Review's traceability gate.",
     "where": [("Reagent inventory", "@@pfas-reagents"), ("Prepared standards", "@@pfas-prep-standards")],
     "who": "bench",
     "effects": [
         ("Prepared standard parent lots", P + "browser/prepared_standards.py", "prepstd.parent_reagents"),
     ]},
]

WHO = {
    "config": "Lab manager or site administrator",
    "site_admin": "Site administrator",
    "bench": "Bench chemists and reviewers, in their own work",
    "system": "Nobody directly: derived by the system",
}


for _e in ENTRIES:                       # the tab an entry is on is kept in one place
    _e["group"] = TAB_OF.get(_e["id"], u"")


def entry(entry_id):
    for e in ENTRIES:
        if e["id"] == entry_id:
            return e
    return None


def grouped():
    """[(group, [entries])] in GROUPS order, each tab in its listed order."""
    by_id = dict((e["id"], e) for e in ENTRIES)
    return [(g, [by_id[i] for i in _TAB[g] if i in by_id]) for g in GROUPS]

