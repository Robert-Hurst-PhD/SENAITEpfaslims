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

Pages carry one line of purpose; a section's header ends in one "?" button
that opens its entry in the panel beside the page (pfas_macros "help",
help_button). Regulatory sources are named as the methods name them, never
by internal tracking numbers.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.html_text import escape as _escape

# The Help page's tabs, in the order the lab works, each with the one line it
# shows.
GROUPS = (
    "Method setup",
    "QC criteria",
    "Bench and extraction",
    "Equipment",
    "Instrument runs",
    "Review and release",
    "Reporting",
    "EDD",
    "Signatures and access",
    "Pages and grids",
)
GROUP_INTROS = {
    "Method setup": "What a method is: its analytes per matrix, standards, factors and limits.",
    "QC criteria": "What each QC must meet, and how a failure is qualified or blocks release.",
    "Bench and extraction": "The extraction batch and its records.",
    "Equipment": "What each piece of equipment owes, and how its checks and readings are recorded.",
    "Instrument runs": "Calibration, the injection list, the import and corrections to a run.",
    "Review and release": "The technical review before a result is released.",
    "Reporting": "How a result is stated on the certificate and which documents are issued.",
    "EDD": "The electronic data deliverable a state receives.",
    "Signatures and access": "Who may sign, approve and sign in where.",
    "Pages and grids": "How a page shows what it holds: wide grids, folded groups and this panel.",
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
     ("edd-profiles", "edd-column-mapped", "edd-qualifiers")),
]

# Which tab each entry is on.
_TAB = {
    "Method setup": ("method-profile", "analyte-matrix", "labelled-standards", "isomers", "integration", "salt-factor",
                     "matrix-factor", "calibration-levels", "holding-time", "project-specs", "project-qapp",
                     "config-history"),
    "QC criteria": ("qc-types", "spike-levels", "recovery-tiers", "recovery-grid", "window-drawer",
                    "eis-limits", "rule-switches", "specifications", "qualified-release", "judged-value",
                    "method-studies", "chart-overlay"),
    "Bench and extraction": ("extraction-batch", "guided-extraction", "traceability", "dilution", "logbooks",
                             "homogenisation", "coc", "expiry-defaults", "certificate-values", "recipes",
              "new-prepared-standard"),
    "Equipment": ("equipment-types", "balance-before-weighing", "temperature-study", "pipette-quarter",
                  "sensor-key"),
    "Instrument runs": ("calibration-decision", "calibration-curve", "ccv-bracketing", "sequence-export",
                        "import-profiles", "manual-integration", "adaptive-integration", "identity-confirmation",
                        "reprocess"),
    "Review and release": ("data-review", "warnings-strip", "qc-standards-table", "publishing-holds",
                           "method-identified", "raw-review"),
    "Reporting": ("rounding", "rl", "non-detect", "qualifier-j", "qualifier-d", "reporting-format", "action-level",
                  "sample-subtypes", "reporting-template", "document-designs", "settings-report"),
    "EDD": ("edd-values", "edd-qualifiers", "edd-profiles", "edd-column-mapped"),
    "Signatures and access": ("sign-rights", "lab-director", "laboratory-page", "people-roles",
                              "time-language", "system-page", "badges", "backups"),
    "Pages and grids": ("navigation", "column-chips", "folded-groups", "help-panel"),
}
TAB_OF = dict((eid, tab) for tab, ids in _TAB.items() for eid in ids)

# The Help button that ends each section's header on the method profile's
# tabs, section id -> entry id. A tab's grid that is no section carries its
# button at the right end of the grid's tools row, keyed by the grid's id.
# A section with no entry of its own opens its tab's overview entry.
SECTION_HELP = {
    # Analytes
    "analytes": "analyte-matrix", "notes": "analyte-matrix",
    # Isotope standards
    "standards": "labelled-standards", "sur": "eis-limits", "engine_fallback": "eis-limits",
    "surscope": "qualified-release", "engine_notes_sur": "eis-limits",
    # QC criteria
    "rules": "qc-types", "windows": "recovery-grid", "xbatch": "extraction-batch",
    # Matrices
    "matrices": "holding-time", "scorr": "matrix-factor",
    # Run & reporting
    "run_template": "ccv-bracketing", "qc_comp": "qc-types", "solv": "traceability",
    "stages": "guided-extraction", "lbl": "extraction-batch", "dil": "dilution",
    "solv_spe": "guided-extraction", "intg": "integration", "rf": "reporting-format", "al": "action-level",
    # Engine
    "names": "method-profile", "engine_mcodes": "method-profile", "qcnames": "qc-types",
    "engine": "calibration-levels", "engine_studies": "method-studies",
}

# The entries a section's Help entry leads on to: the panel ends the entry
# with a Related line, one button per entry, each opening in the same
# panel. Keyed by the entry a section, a grid or a Run Builder step opens.
RELATED = {
    # the Analytes grid: what its reported cells, isomer and salt columns mean
    "analyte-matrix": ("rl", "isomers", "salt-factor"),
    # the Run Builder's first step: the dilutions it plans, the import that follows
    "guided-extraction": ("dilution", "import-profiles"),
    # the QC criteria tab: the rules table, and the tiers behind the recovery grid
    "qc-types": ("rule-switches",),
    "recovery-grid": ("recovery-tiers", "window-drawer"),
    # the Certificate format section: the two qualifiers its settings decide
    "reporting-format": ("qualifier-j", "qualifier-d"),
}

P = "src/senaite/pfas/"
W = "pfas_pipeline/"

ENTRIES = [
    # ── Method studies ────────────────────────────
    {"id": "method-studies", "term": "Method studies (MDL, MRL, precision and accuracy, DL)",
     "text": "A study is calculated from results the runs already stored, for one method "
             "and matrix. Its design names the preparations (the blanks and the method's spike "
             "levels for the matrix, at their concentrations), the replicates per level and the "
             "days; each day is one part, given to an analyst as its own worksheet. Annual MDL: 40 CFR 136 Appendix B Revision 2: the greater of "
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
     "where": [("Run & reporting tab", "@@pfas-method-profiles")],
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
     "where": [("Run & reporting tab", "@@pfas-method-profiles")],
     "who": "system",
     "effects": [
         ("Detected versus the RL (U qualifier)", P + "coa_format.py", "judged < rl"),
         ("Recovery and RPD windows", W + "qc_engine.py", "judged = profile.judged_pct(recovery_pct, matrix)"),
         ("Method blank, MDL and duplicate detection", W + "run_queue.py", "profile.judged_conc("),
         ("A run judged under another rule is held", P + "coa_qc_standards.py", "\"rule_changed\""),
     ]},
    {"id": "rl", "term": "Reporting limit (RL)",
     "text": "The lowest concentration reported as a number; below it a result is a "
             "non-detect. It is the RL typed on the method's Analytes tab, else "
             "the method's lowest calibration level in the reporting unit. A diluted "
             "result's RL is multiplied by the dilution.",
     "where": [("Analytes tab", "@@pfas-method-profiles")],
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
     "where": [("Run & reporting tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Certificate wording", P + "coa_format.py", "def format_result"),
         ("EDD concentration and qualifier", P + "edd_builder.py", "codes = [\"N.D.\"]"),
     ]},
    {"id": "reporting-format", "term": "Certificate format (Reporting tab)",
     "text": "The certificate settings per method and matrix: which columns show, how "
             "non-detects print, significant figures, rounding rule and the notes. A "
             "\"All matrices\" shows the method's default; a matrix row's blank cell, a "
             "muted \u00b7, inherits from it. Certificates use "
             "these settings as they were when the reporting template was issued.",
     "where": [("Run & reporting tab", "@@pfas-method-profiles"), ("Reporting Template", "@@pfas-report-template")],
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
     "where": [("Regulatory Limits", "@@pfas-regulatory-limits"), ("Run & reporting tab", "@@pfas-method-profiles")],
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
             "matrices, recovery tiers, isotope standards, calibration and CCV "
             "criteria, reporting limits and certificate format. The pipeline and the "
             "certificate read it; nothing keeps a second copy. Each tab's groups are "
             "sections that open and close, each with a one-line summary of what it "
             "holds; a tab opens with its sections closed and this browser remembers "
             "which you opened. A section's ? opens its Help entry in a panel beside "
             "the page, which stays open while you edit. The bar at the foot says what is unsaved on the tab, "
             "counted by kind (cells, tiers, rows, rules, settings), with Discard and "
             "Save; the tab's name carries a dot until it is saved.",
     "where": [("Method Profiles", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Exported to the pipeline on every save", P + "method_profile_store.py", "def export_profiles_to_file"),
         ("The sections you opened, kept per method and tab", P + "browser/static/method_profile_edit.js", "pfas.mp.sec."),
         ("The foot bar names what is unsaved", P + "browser/templates/method_profile_edit.pt", "'Unsaved changes in '"),
         ("A section's Help opens beside the page", P + "browser/static/pfas-components.js", "function openHelp(btn)"),
     ]},
    {"id": "recovery-tiers", "term": "Recovery tiers",
     "text": "The recovery windows per QC type, by analyte group (key analytes, "
             "analytes with their own isotope standard, analytes without one) and by "
             "matrix: a tier applies in all matrices or in the matrices listed for it. "
             "Each listed tier has its own list, a search box named after the tier; a "
             "tier whose list is empty applies nowhere until matrices are added. The "
             "first tier that matches an analyte and matrix sets its window. A "
             "low-level tier applies only to spikes at or below a set multiple of the RL.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Judged by the pipeline per analyte and matrix", W + "qc_engine.py", "def recovery_check_profiled"),
         ("The matrices a tier applies in", P + "qc_tiers.py", "def tier_matrices(profile_data, tier)"),
         ("An empty list is shown as applying nowhere", P + "browser/static/pfas-components.js", "applies nowhere until you add some."),
         ("Low-level tier needs the spike level and the RL", W + "method_profiles.py", "LOW_LEVEL_KEY = \"low_level_x_rl\""),
     ]},
    {"id": "recovery-grid", "term": "Recovery window grid",
     "text": "The window each analyte is judged by in each matrix, for one QC type "
             "(Show) and one spike level at a time. Matrices whose windows agree for "
             "every analyte share a column headed by their names. Each analyte group "
             "opens folded to one row with its count and windows; open it to see "
             "each analyte, and the page remembers it. An analyte a matrix does not "
             "report reads not reported. A window in full "
             "weight with a teal edge is set on this cell: it comes from a tier listing "
             "this matrix. A muted window comes from a wider tier or the method's "
             "default. A dash means no window, and the analyte is flagged NO WINDOW. "
             "The legend under the pickers repeats this. Nothing is stored "
             "per cell; every window belongs to a tier. Low-level recoveries covers "
             "the recovery checks: while it is Off, Low level is locked for LFB and "
             "LFSM; LFSMD RPD and SD RPD still show and judge their low-level tiers.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Matrices that agree share a column", P + "profile_grids.py", "def _matrix_columns(mps, profile, grids, qc_type)"),
         ("The legend line", P + "profile_grids.py", "WINDOWS_LEGEND = ("),
         ("A folded group says what its analytes hold", P + "profile_grids.py",
          "def group_summary(members, columns, group=None)"),
     ]},
    {"id": "window-drawer", "term": "Window cell drawer",
     "text": "Opens on the recovery grid's cell you click: the analyte, its matrices "
             "and the QC type, with Prev and Next; the window on a 0 to 200 % bar; Set "
             "by, naming this cell's tier, a wider tier or the method's default; and the "
             "tier's own editor (name, which analytes, its matrices, the window). New "
             "tier for selected cells adds a tier for this matrix ahead of the one that "
             "sets the cell. Every reset is named for what it leaves: Reset to tier X "
             "when another tier takes over, Reset cell to method default only when the "
             "default does. A reset can be undone until Save.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("A new tier ahead of the one that sets the cell", P + "browser/static/method_profile_edit.js", "action(\"New tier for selected cells\""),
         ("The reset named for the method default", P + "browser/static/method_profile_edit.js", "action(\"Reset cell to method default\""),
     ]},
    {"id": "rule-switches", "term": "QC rule states",
     "text": "How each check the pipeline runs for a method is held, one row per rule "
             "on the QC criteria tab: Enforced (a failure holds release), Evaluate "
             "(judged and flagged at Data Review, never holds) or Off (not judged; its "
             "limits stay). The QC types' rows (LCS, LFB and LFSM recovery, LFSMD and "
             "duplicate RPD), the blank rows (method blank, LRB, matrix blank, CCB, FRB, "
             "trip blank) and Low-level recoveries have the same three states. An Off "
             "row owes no limit; an Enforced or Evaluate row without one is reported as "
             "unconfigured, and its Effective limits read no limit set (coral when "
             "Enforced). A state drawn outlined is the method's default (its Scope ends "
             "in a muted \u00b7 default); a filled one is set on this method. A project's QAPP "
             "switch turns a type Off for its batches; "
             "switched on, an Evaluate type stays Evaluate and a type the method has "
             "Off runs Enforced. An Evaluate failure is shown at Data Review but does "
             "not hold release.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "lists": ["rule_switches"],
     "effects": [
         ("Read by the pipeline before each check", W + "run_queue.py", "_rule_enabled(toggles,"),
         ("One reader for every row's state", P + "qc/rules.py", "def rule_state("),
         ("A project's switch keeps the method's state", P + "qc/rules.py", "def qc_row_switched("),
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
             "different reviewer, and its before and after pages are stamped. That is the "
             "vendor flow and it is unchanged. An edit made on the Raw Data tab is signed "
             "differently: it needs no reason when it is made, and its reasons and the "
             "analyst's initials are given once, in the Manual changes panel at the end of "
             "review, then a different person countersigns at verify; the panel names the line each "
             "edit used, valley to valley, perpendicular drop, flat baseline or tangent skim, and "
             "any levels set by hand. Every page "
             "of the report carrying the lab's heading (found by scanning the report on "
             "upload) must be listed or dismissed with a reason, countersigned. Never to make QC pass (a state accreditation programme's manual-integration guidance).",
     "where": [("Import Studio", "@@pfas-import-studio"), ("Data Review", "@@pfas-data-review"),
               ("Reasons", "@@pfas-mi-reasons")],
     "who": "bench",
     "effects": [
         ("Raw Data edits are initialled once at the end of review", P + "manual_integration.py", "the analyst's initials"),
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
    {"id": "adaptive-integration", "term": "Adaptive integration and the raw peak card",
     "text": "The Adaptive engine follows the peak-finding method published by Nagura Lab "
             "(naguralab.com/integration), re-implemented from its description. The noise is "
             "read from the trace's point-to-point differences with every peak, and every "
             "neighbouring isomer, left out; a peak starts where the smoothed slope rises above "
             "the method's sensitivity times the slope's spread and ends where it settles; a flat "
             "stretch above the shoulder split is a shoulder; touching peaks share one straight "
             "baseline split by drop lines. Each peak is measured for its width at half height, "
             "its tailing and its plates. On Data Review's Raw Data tab each analyte's card "
             "names its Engine, Classic when the peak says none, and shows, where the peak has "
             "them, the Qualifier S/N, FWHM in seconds, Tailing, Plates, Smoothing as the number "
             "of points the filter ran over, twice the half-width plus one, with the calibrator "
             "it was learnt from, and the File transition where the file's "
             "differs from the method's. The peak's note says anchor not found, a baseline dip, "
             "or how many peaks a summed row adds. A Gaussian or EMG area refused for the "
             "trapezoid reads Fit refused with the reason; a pair fit that failed while the area "
             "kept its own fit reads Pair fit failed; either marks the card for review.",
     "where": [("Data Review", "@@pfas-data-review"), ("Run & reporting tab", "@@pfas-method-profiles")],
     "who": "bench",
     "effects": [
         ("The method, re-implemented", W + "raw_adaptive.py", "re-implemented from its description"),
         ("The noise leaves out the peaks and excluded spans", W + "raw_adaptive.py", "def robust_sigma(y, keep=None):"),
         ("The peak's measures recorded", W + "raw_run.py",
          "for key in (\"fwhm_s\", \"tailing\", \"plates\", \"smoothing\", \"smoothing_from\", \"engine\", \"fit_note\"):"),
         ("The card's values", P + "raw_review.py", "def _measures(peak, row):"),
         ("Classic when the peak names no engine", P + "raw_review.py", "ENGINES.get(peak.get(\"engine\") or u\"classic\""),
         ("Fit refused, with its reason; Pair fit failed", P + "raw_review.py", "def _fit_text(peak):"),
         ("Smoothing shown as the points filtered over", P + "raw_review.py", "2 * int(m) + 1"),
         ("A refused or failed fit marks the card for review", P + "raw_review.py",
          "a refused or failed fit is for review"),
         ("Anchor not found", W + "raw_run.py", "ANCHOR_NOT_FOUND = \"anchor not found\""),
     ]},
    {"id": "identity-confirmation", "term": "Identity confirmation (single transition)",
     "text": "FDA C-010.04 §10.2(4): PFBA and PFPeA have one usable MS/MS transition, "
             "so a positive must be confirmed by a second, independent technique "
             "agreeing within the method's % difference. The reviewer is asked; an "
             "unconfirmed result is released with the CONF qualifier.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Prompted for a detected PFBA / PFPeA", W + "qc_engine.py", "def single_transition_confirm_needed"),
     ]},
    {"id": "holding-time", "term": "Holding time",
     "text": "Three clocks, each set per method and matrix on Storage and holding: the "
             "sample (collection to extraction), the processed sample (homogenisation "
             "complete to extraction, for a homogenised sample only) and the extract "
             "(extraction to analysis). A sample past its clock fails the Chain of Custody "
             "gate of Data Review whatever the checkbox says. Each kept item also has the "
             "temperature it is stored at; a fridge or freezer is judged against the range "
             "for what it holds. Nothing is preset: the lab enters each temperature and time. "
             "A matrix with no sample holding time has its Sample holding set to None, "
             "which reads a dash; a None holding never stops the matrix being removed.",
     "where": [("Matrices tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Computed for the Chain of Custody gate", P + "browser/data_review.py", "def holding_time_summary"),
         ("No holding time for a matrix", P + "profile_grids.py", "\"No holding time for {0}\""),
     ]},
    {"id": "specifications", "term": "Specifications",
     "text": "The recovery windows each method (or a project's batches) is judged "
             "against. They are part of the method profile (its recovery tiers); a project's "
             "Specs change them for its batches. SENAITE's own Analysis Specifications "
             "are not used, because they would judge a concentration against a recovery "
             "window.",
     "where": [("QC criteria tab", "@@pfas-method-profiles"), ("Projects", "@@pfas-projects")],
     "who": "system",
     "effects": [
         ("A project's batches run to its effective profile", P + "project_specs.py", "def effective_for_project("),
     ]},
    {"id": "analyte-matrix", "term": "Analyte \u00d7 matrix",
     "text": "Which of the method's analytes are reported in which matrix. Each cell "
             "under Reported in, with RL is \u2713 (reported; its RL shows instead when "
             "one is set) or \u2717 (left out, drawn muted). A left-out analyte is left "
             "out for that matrix everywhere: QC checks, certificates and the EDD. Click "
             "a cell to set Reported and the RL together: Escape discards, a click "
             "elsewhere keeps it. \u2713 all under a matrix reports every analyte in it. "
             "Until the analyte set is checked against the published method a banner "
             "asks for it; Confirmed records who and when, and Verify again asks for the "
             "check again after the set changes. Ticked rows open the bulk bar: Edit "
             "selected, or a one-column action (set Quantified by, set the panel for a "
             "matrix, copy a column, reset to inherited) that applies at once and can be "
             "undone until the next action or Save.",
     "where": [("Analytes tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read by the pipeline per matrix", W + "method_profiles.py", "inclusion = data.get(\"analyte_matrix_inclusion\")"),
         ("A flag and the RL in one cell", P + "profile_grids.py", "PANEL_GROUP = \"Reported in, with RL\""),
         ("The one-column actions", P + "profile_grids.py", "ANALYTE_ACTIONS = ["),
         ("Verify again asks for the check again", P + "browser/templates/method_profile_edit.pt", "form=\"analytes-verify\">Verify again</button>"),
     ]},
    {"id": "labelled-standards", "term": "Isotope standards",
     "text": "Every isotope standard the method uses, its role (SUR, an extracted "
             "standard, or IS, an injection standard) and the native analytes linked "
             "to it. An analyte linked to the isotope analogue of its own compound has "
             "its own isotope standard; the others fall in the \"no isotope standard\" "
             "tier. Add and Remove sit above the grid; a standard that quantifies a "
             "native cannot be removed. The row menu, at the row's end, sets the role and edits the link and limits, "
             "copies the Aqueous limits to every class, resets the classes to Aqueous, "
             "or removes the standard. Where the method has SUR limits, Source holds the "
             "method table they come from and reads VERIFY until they are confirmed.",
     "where": [("Isotope standards tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("The row menu", P + "browser/static/pfas-components.js", "label: \"Copy Aqueous to every class\""),
         ("The Source column", P + "profile_grids.py", "Column(\"source\", \"Source\", \"text\")"),
         ("Decides the \"no isotope standard\" analytes", P + "method_profile_sections.py", "def no_std_set"),
         ("Surrogate versus internal-standard checks", W + "qc_engine.py", "get_labelled_roles(method_id)"),
     ]},
    {"id": "isomers", "term": "Isomers (linear and branched)",
     "text": "An analyte measured as separate linear and branched peaks is reported as "
             "one summed result under its reported name; the peaks are summed before the "
             "salt and matrix factors. The individual peaks stay visible only for the "
             "laboratory's own review (control charts, retention time, calibration).",
     "where": [("Analytes tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Peaks summed by the pipeline", W + "pipeline.py", "def _sum_isomer_pair"),
         ("Reported name on every page and the certificate", P + "isomers.py", "def label(profile, keyword, titles)"),
     ]},
    {"id": "integration", "term": "Integration (raw data)",
     "text": "How the LIMS integrates a run imported from the instrument's raw data: the "
             "smoothing that finds each peak, the baseline, how the area is measured and the "
             "smallest signal-to-noise reported, then each compound's transitions, retention "
             "time and window. An analyte with isomers is integrated as lr and br rows: the "
             "linear peak is its lr row, and each br row covers the peaks in its own window, "
             "less the linear peak; the two are quantified apart and summed only at reporting. "
             "A linear peak is a single peak. A co-eluting pair, fitted with its partner, is "
             "Classic only: Adaptive refuses it. "
             "FOSA is integrated whole. Where results come from can change at any time: the "
             "instrument software; Validation, which reports the software's results and keeps "
             "the LIMS's for comparison; or LIMS integration, which reports the LIMS's own. "
             "The engine is Classic, where a fixed smoothing finds each peak, or Adaptive, where "
             "the slope of the signal finds each peak and splits its shoulders; Adaptive's "
             "sensitivity, shoulder split and qualifier apex tolerance are "
             "shown only for it, Classic's baseline only for Classic, and Adaptive's smoothing may be auto: the half-width is then learnt "
             "for each compound from its median-concentration calibrator whose quantifier "
             "has not overflowed and holds a peak, or its middle level where the calibrators state "
             "no concentration for it, and each peak names that calibrator. Adaptive's "
             "expected time is Fixed, each peak sought at its own retention time, or Isotope "
             "standard, where a native's time moves with its quantitation standard's found time "
             "in each injection; a standard not found leaves the native at its own time with "
             "the note anchor not found. The transition tolerance is how far a "
             "file's transition may lie from the method's on both Q1 and Q3: the nearest within it "
             "is read, the peak names the file's transition where it differs, and two equally near "
             "refuse the run. Each qualifier is integrated at the quantifier's apex; the first "
             "qualifier's signal-to-noise is the row's qualifier S/N. On a summed row, a br "
             "cluster or FOSA, the qualifier is the peak at the tallest member's apex, so the ion "
             "ratio is that peak over the summed quantifier; the calibrators share that basis. "
             "A compound's Qualifier "
             "detection S/N decides only whether its qualifier is found, the method's confirmation "
             "value when blank; the method's confirmation S/N alone decides whether the identity is "
             "confirmed. The largest fit deviation is shown "
             "for a Gaussian or EMG area under either engine: a fitted area further than it from "
             "the trapezoid over the same edges, or a fit that fails, falls back to that "
             "trapezoid, and the peak says why. "
             "An analyst's re-integration or another apex, on a quantifier or a qualifier, is "
             "refused when its area lies less than the smallest manual change from the "
             "automatic area, 5 % when blank, or its S/N is under the smallest S/N for a manual "
             "peak, judged against the noise the automatic peak was read against; blank, the "
             "S/N is not judged. A deleted peak is never refused, but a calibrator whose peak, "
             "or whose isotope standard's, was deleted comes off its curve, and more such "
             "calibrators on one analyte's curve than the method's Most calibrators dropped, "
             "on the Calibration tab, fails its calibration check; overflowed or undetected "
             "calibrators are not counted. "
             "Edge points, beside Smoothing under Classic, 6 when blank, is the number of raw points "
             "averaged at each baseline end: it sets every automatic Classic baseline, so it "
             "changes the automatic peaks. "
             "The Peak review group holds the rules for a dropped baseline and for the "
             "candidates offered: Fewest points in a peak; Edges past the tail; Valley limit "
             "for a perpendicular drop; Tangent skim ratio; the Peak search slope, amplitude "
             "and smoothing, which Add peak at cursor searches with; Fewest points in a "
             "candidate; and Smallest candidate width. A blank is the default, drawn in the "
             "box: 5 points, 2 sigma, 25 %, 25 %, 0.7, the smallest S/N for a manual peak when "
             "set else 3, 50 %, 3 points and 40 %. A compound's column overrides each but the "
             "search slope and smoothing, and has its own Edge points. Raising a candidate "
             "setting can leave a saved apex choice unapplied until it is undone. "
             "A compound's Smoothing, Area, Smallest S/N, Sensitivity, Expected time and manual-peak "
             "columns override the "
             "method defaults for its transitions; blank uses the default. The change log under "
             "the section lists every change to where results come from, the defaults and "
             "each compound's settings, with who and when. With Instrument software "
             "chosen, only the choice and the log are shown.",
     "where": [("Run & reporting tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("A compound's own smallest S/N", P + "method_profile_sections.py", "cf.Field(\"min_sn\", u\"Smallest S/N\""),
         ("The engine and its settings", P + "method_profile_sections.py", "cf.Field(\"engine\", u\"Engine\""),
         ("Expected time", P + "method_profile_sections.py", "cf.Field(\"rt_anchor\", u\"Expected time\""),
         ("Smoothing learnt per compound", W + "raw_run.py", "def learn_smoothing("),
         ("The rules for a dropped baseline", P + "raw_preview.py", "def review_limits("),
         ("Edge points", W + "raw_integrate.py", "def _edge_level(y, i, step, points=EDGE_POINTS)"),
         ("The change log", P + "method_profile_sections.py", "def integration_log("),
         ("Settings read for a raw run", W + "method_profiles.py", "def get_integration(method_id: str) -> dict"),
         ("Peaks integrated", W + "raw_integrate.py", "def integrate(t, y, rt, window, settings)"),
         ("A fitted area falls back to the trapezoid", W + "raw_integrate.py", "def gated_fit("),
         ("The transition tolerance", P + "method_profile_sections.py", "cf.Field(\"mz_tolerance\", u\"Transition tolerance\""),
         ("The nearest file transition, two equally near refused", P + "raw_mzml.py", "def match_transition(wanted, available, tol):"),
         ("A compound's qualifier detection S/N", P + "method_profile_sections.py",
          "cf.Field(\"min_qual_sn\", u\"Qualifier detection S/N\""),
         ("The row's qualifier S/N", W + "raw_run.py", "def _qual_sn("),
         ("A manual change refused under the method's limits", P + "raw_preview.py", "def edit_problem("),
         ("The limits, the compound's over the method's", P + "raw_preview.py", "def manual_limits("),
         ("Calibrators dropped by hand, counted", W + "qc_engine.py", "def manual_cal_drops("),
         ("A qualifier's floor", W + "raw_run.py", "def _qual_floor("),
         ("Isomer peaks summed only at reporting", W + "raw_run.py", "keep their names on the rows; they are summed only at reporting"),
     ]},
    {"id": "salt-factor", "term": "Salt factor",
     "text": "The molar-mass correction for a standard supplied as a salt: molar mass of "
             "the free acid divided by that of the salt (1.0 = none). Each is tied to "
             "the reference-standard lot (CoA) it comes from. It is not applied to an analyte "
             "whose calibration lots, as loaded for the run, were all made from certificate "
             "values stated as the acid (concentrations calculated from their recipe): those "
             "are already on the acid basis. A lot with typed concentrations keeps the factor.",
     "where": [("Analytes tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Applied by the pipeline per analyte", W + "pipeline.py", "salt_factors = _get_salt_factors(method_id)"),
         ("Analytes on an acid basis, from the run's calibration lots", P + "run_lots.py", "def acid_analytes("),
     ]},
    {"id": "sample-subtypes", "term": "Sample sub-types",
     "text": "Optional sub-types of a sample type (Meat / Muscle: Beef, Pork, Venison). A CoC "
             "sample of the type picks one. A regulatory limit that names sub-types applies only "
             "to samples of those sub-types, and for them replaces the type-wide limit of the same "
             "program on the same analytes; a limit that names none applies to every sample of the "
             "type. A sub-type is offered for the method profiles that analyse its type and uses "
             "their settings for the type; turn a profile off on a sub-type's row if it does not "
             "analyse that sub-type. A sub-type a limit or a sample names is not removed.",
     "where": [("Configuration, Sample Sub-types", "@@pfas-sample-subtypes")],
     "who": "config",
     "effects": [
         ("The sub-types of a type", P + "sample_subtypes.py", "def from_form("),
         ("Which limits apply", P + "regulatory_limits.py", "def applicable("),
     ]},
    {"id": "new-prepared-standard", "term": "New Prepared Standard",
     "text": "One prep sitting, made from a recipe of the method on the chosen prep log. Saving "
             "writes one entry in that log: who, when, the equipment, the lots used and the lots "
             "made. A series makes one lot per level, named from the method's code and the level "
             "and numbered by the prep date. Change the volume prepared to make a larger batch; "
             "the parent amounts scale with it. Concentrations are calculated when saved, from the "
             "lots picked and the volumes measured; expiry is the prep date plus the recipe's shelf "
             "life, no later than the earliest parent's. Each lot is pinned to the recipe revision "
             "that made it. A lot made before recipes keeps its typed concentrations, marked typed.",
     "where": [("Prepared Standards", "@@pfas-prep-standards")],
     "who": "bench",
     "effects": [
         ("The lots a sitting makes", P + "prep_sitting.py", "def build("),
         ("One entry in the prep log", P + "prep_entries.py", "def make("),
     ]},
    {"id": "recipes", "term": "Recipes",
     "text": "Each recipe says how the lab prepares one standard or reagent: what it is "
             "made from, the prep log that records it (FM-ENV-001 or 002), its steps, shelf "
             "life and storage, and what is made from it. Purchased materials are not "
             "recipes; they appear as the parents. A calibration recipe can make a series in "
             "one sitting, serially or each level from the stock. Concentrations are "
             "calculated, never typed: each level = the parent lot's concentration \u00d7 "
             "volume taken \u00f7 final volume, a purchased parent's from its lot's "
             "certificate values as the acid, an in-house parent's from its own recipe. "
             "Amounts are the lab's own. Saving issues a new revision; preps already made "
             "keep the revision they followed. A recipe with no shelf life takes its log's "
             "default expiry.",
     "where": [("Logbooks, 4 \u00b7 Recipes", "@@pfas-recipes")],
     "who": "config",
     "effects": [
         ("Revisions", P + "recipes.py", "def new_revision("),
         ("Calculated concentrations", P + "recipe_calc.py", "def resolve("),
     ]},
    {"id": "certificate-values", "term": "Certificate values",
     "text": "A purchased standard lot's analytes, typed exactly as its certificate states "
             "them: the value already allows for purity. Each analyte is one of the "
             "methods' compounds; its CAS is the compound's, shown, never typed. Most certificates state every "
             "analyte as the acid even when the neat material was a salt; a value stated as "
             "a salt is converted to the acid with the molecular weights the lab enters: "
             "Acid = Salt \u00d7 MW(acid) \u00f7 MW(salt) (EPA 537.1 \u00a77.2.3). Recipes calculate "
             "from the acid. Whoever enters certificate values can correct them; each "
             "correction needs a reason and keeps the value it replaced, and saving one "
             "flags every lot made from the lot, and every run that used them, for review. "
             "Nothing is recalculated until a reviewer does it.",
     "where": [("Reagent Inventory", "@@pfas-reagents")],
     "who": "bench",
     "effects": [
         ("Converted to the acid", P + "recipe_calc.py", "def as_acid("),
         ("A correction flags the lots made from it", P + "browser/reagents.py", "def _handle_save_certificate("),
     ]},
    {"id": "matrix-factor", "term": "Matrix factor and sample correction",
     "text": "How a concentration in the extract becomes one in the sample: reported = "
             "instrument \u00d7 factor, one factor per matrix, or back-calculated from "
             "each sample's logged amount and extract volume. The RL derived from the "
             "calibration levels uses the same factor.",
     "where": [("Matrices tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read by the pipeline per matrix", W + "method_profiles.py", "def get_matrix_factor"),
         ("The derived RL", P + "calibration_levels.py", "matrix_factors"),
     ]},
    {"id": "qc-types", "term": "QC types",
     "text": "The batch QC samples a method runs (method blank, LFB / LCS, LFSM, "
             "LFSMD, duplicate): a type runs while its row on the rules table is "
             "Enforced or Evaluate. The row of a type the method holds counts the "
             "analytes that have no window yet.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Which QC types the pipeline judges", P + "qc/qc_types.py", "def enabled_qc_types"),
     ]},
    {"id": "ccv-bracketing", "term": "CCV bracketing",
     "text": "A continuing calibration verification is run after every N counting "
             "injections (field samples and extraction QC; not calibrators or the ICV), "
             "and a closing CCV ends the run. N is the method's CCV frequency; the Run "
             "Builder inserts the CCVs. In the method's run template the calibrator line "
             "expands to the calibration standards when the curve is included, and the "
             "field samples line can be moved but not removed.",
     "where": [("Run & reporting tab", "@@pfas-method-profiles"), ("Run Builder", "@@pfas-run-builder")],
     "who": "config",
     "effects": [
         ("Spacing checked by the pipeline", W + "qc_engine.py", "def ccv_frequency_check"),
     ]},
    {"id": "dilution", "term": "Dilutions",
     "text": "A dilution can be planned when the run is built: it never replaces the undiluted injection, runs with this run or separately, and is prepared and recorded in step 4. A sample that read above the calibration range is re-injected diluted. "
             "The dilution is logged as a total fold (e.g. 10); the diluted result is "
             "reported as a retest of the analysis, with its own time and an RL "
             "multiplied by the fold. Each method says which routes it allows (Lab "
             "Workflow, Dilutions): dilute the extract; a smaller aliquot, diluted to volume "
             "before the EIS and extracted again in the next extraction batch; or the EIS "
             "re-spiked into the diluted extract, a method modification whose result is "
             "qualified. A dilution's surrogate (EIS) is judged only when it was added to the "
             "dilution, against the method's window, the lowest EIS recovery in a diluted "
             "extract as its low end when set; a dilution without it added is not judged. "
             "The method chooses whether a diluted reading is multiplied by the fold always, "
             "or only when the standard that quantifies the analyte was added to the "
             "dilution. A re-spiked result is qualified when the method says so, with the "
             "code and wording the QAO sets in QC Qualifiers. The largest dilution, that "
             "lowest recovery, the smallest aliquot and the client's approval are the lab's, "
             "from its SOP; nothing is preset, and a project can override any of them.",
     "where": [("Extraction Guide", "@@pfas-extraction-guide"), ("Run & reporting tab", "@@pfas-method-profiles")],
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
    {"id": "raw-review",
     "term": "Editing raw traces",
     "text": "Data Review's Raw Data tab shows every chromatogram of the run as a small thumbnail, by "
             "compound, one analyte across every injection, or by injection, every analyte of one "
             "injection. Click a thumbnail to open its card in a dialog. The card shows the Quantifier "
             "and Qualifier switch, the trace with its zoom tools, a readout of "
             "area, retention time, S/N, ion ratio, concentration with its unit and how the peak was "
             "integrated, the flags as chips, and Details for the engine, smoothing, FWHM, tailing, "
             "plates and the file's transition. Previous and Next, or PageUp and PageDown, walk the "
             "grid without closing the dialog and ask first when a change is not applied. "
             "A peak is edited on the chart. The baseline is drawn as a line with a hollow handle at "
             "each end. Drag a handle sideways to move that edge to the nearest sample. Drag it up or "
             "down to set that end's level by hand, within the trace's counts; hold Shift, or "
             "double-click the handle, to put the level back on the signal. Drag the line itself to "
             "move both edges together. A right-click on the chart, the Actions button and the menu "
             "key open the same menu: Set start here, Set end here, Drop baseline here, Baseline, "
             "Peaks found, Add peak at cursor, Split at cursor, Delete peak, Undo edit, Restore "
             "automatic, Zoom to peak, Zoom to window and Copy values. An entry that cannot act is "
             "shown with the reason, and each entry's key is shown beside it. The wheel zooms the time "
             "axis and dragging the axis pans it. Above the chart, the magnifiers zoom in and out, the "
             "dashed box zooms to a box dragged on the chart, and the corners go back to the whole "
             "window; zoomed, the counts fit what is shown. "
             "The baseline has four modes. Valley to valley joins the two edge levels, the line for a "
             "peak that stands clear. Perpendicular drop draws one line under a pair of touching "
             "peaks, from the outer edge of the pair, and measures each peak above it; it applies "
             "where a neighbouring peak shares the valley. Tangent skim is for a small rider on the "
             "tail of a tall peak: the line runs from the signal at the rider's start to the signal at "
             "its end, so the tall peak's tail is not counted in the rider. Flat at the lower edge is "
             "a horizontal line at the lower of the two edge levels. Where no neighbour is found a "
             "drop is the valley line, and the menu says so. A level set by hand replaces the level "
             "its mode reads: the line between the two levels for valley and skim, flat at the lower "
             "of them for flat, and the line's value at the pair's outer edges for a drop. Whatever "
             "the method's area setting, a manual edit's area is the trapezoid of the signal above the "
             "line the analyst chose. "
             "Peaks found lists the other peaks the worker found in the window, each with its time, "
             "area and S/N, and a click chooses one. Another apex is chosen only on a single peak, and "
             "it names the peak whose own apex it is. A candidate is offered only when at least the "
             "method's Fewest points in a candidate of its raw samples stand at or above half its "
             "height, 3 by default, and its width is at least Smallest candidate width of the "
             "automatic peak's, 40 % by default, so a fragment on a tall peak's tail is not offered. "
             "At coarse sampling a narrow real peak can fall under it: lower the value for that "
             "compound or set the edges by hand. The choice is judged on the candidate's own area "
             "against the automatic peak's stored area. Add peak at cursor searches from the cursor "
             "for a peak above the compound's Peak search amplitude and fills in its edges; Split at "
             "cursor cuts the automatic peak at the cursor with a perpendicular drop, where a "
             "neighbour lies across it. Both are re-integrations. "
             "The card previews the new peak with the worker's own arithmetic and refuses an edit in "
             "the worker's words when its area is less than Smallest manual change from the automatic "
             "area, when its S/N is under Smallest S/N for a manual peak, when it holds fewer points "
             "between its edges than the method's Fewest points in a peak, when a level set by hand "
             "lies outside the trace's range, or when a perpendicular drop or tangent skim reads past "
             "the part of the trace kept at full resolution. Two of these are judged on the same edit "
             "in that order: the levels, then the fewest points. A valley above the method's Valley "
             "limit for a perpendicular drop, a skim above its Tangent skim ratio, and an edge nearer "
             "its apex than the method's Edges past the tail are noted as chips, never refused. A "
             "deleted peak is exempt from the first rule. A trace stored before the run was last "
             "processed may ask for the run to be processed again before a drop or skim can be "
             "measured on it. "
             "A deleted quantifier makes the analyte N.D.; a deleted qualifier makes the result N.C. "
             "on every run, whatever the S/N rule; and the ion ratio is taken from the qualifiers "
             "left. A qualifier is read only beside a quantifier peak, so a qualifier edit is refused "
             "while the quantifier has none, and one made before reads No effect, saying why, and asks "
             "no reason or signature. An edit the run cannot make, such as levels off the trace or a "
             "span too short to measure, is kept the same way. Deleting an isotope standard's peak "
             "asks for a confirmation that names the natives that lose their concentration, and takes "
             "that injection's calibrators off the curve. An edit needs no reason when it is made, and "
             "the card shows it as waiting until the run is processed again; submit and release wait "
             "until it has been. At the end of review the Manual changes panel lists every edit with "
             "the line and levels it used: the analyst gives a reason for each and initials once, and "
             "the verifier's Approve Release countersigns them, saved only once the worksheet is "
             "verified. Initials need the preparer sign right in People & Roles and the countersign the "
             "reviewer sign right. The verifier cannot be the analyst who initialled, or anyone who "
             "edited the peak since its last undo. An edit in the run's file that no change lists "
             "holds submit and release until it is undone. A method can also set Most calibrators "
             "dropped: more manual deletions than that on one analyte's curve fails its calibration "
             "check, and the Calibration tab names the levels and holds Approve.",
     "where": [("Data Review", "@@pfas-data-review")],
     "who": "bench",
     "effects": [
         ('The overview is by compound or by injection', P + 'browser/static/raw_data.js', 'By compound'),
         ('The baseline handles and the menu', P + 'browser/static/raw_data.js', 'Drop baseline here'),
         ('The four baselines', P + 'browser/static/raw_data.js', 'Flat at the lower edge'),
         ('Peaks found', P + 'browser/static/raw_data.js', 'Peaks found'),
         ('Add a peak at the cursor', P + 'browser/static/raw_data.js', 'Add peak at cursor'),
         ('Split at the cursor', P + 'browser/static/raw_data.js', 'Split at cursor'),
         ('A peak is deleted from its card', P + 'browser/static/raw_data.js', 'Delete peak'),
         ('Restore automatic', P + 'browser/static/raw_data.js', 'Restore automatic'),
         ('The Actions button', P + 'browser/templates/data_review.pt', 'Actions'),
         ('The baseline is one of four', P + 'browser/static/raw_data.js', 'The baseline is Valley, Drop, Flat or Skim.'),
         ('Another apex only on a single peak', P + 'browser/static/raw_data.js', 'Another apex is chosen only on a single peak.'),
         ('Another apex is the peak whose own apex it is', P + 'raw_review.py', 'Two peaks share the apex at'),
         ("An isotope standard's deletion is confirmed", P + 'raw_edit.py', 'Confirm to delete its peak in'),
         ("The tab's edits are one form", P + 'browser/templates/data_review.pt', 'form id="raw-edit"'),
         ('Smallest manual change', P + 'method_profile_sections.py', 'Smallest manual change'),
         ('Smallest S/N for a manual peak', P + 'method_profile_sections.py', 'Smallest S/N for a manual peak'),
         ('Fewest points in a peak', P + 'raw_review.py', 'a manual peak needs at least'),
         ('Levels outside the trace', P + 'raw_review.py', "lie outside the trace's range"),
         ('A drop or skim must stay inside full resolution', P + 'raw_edit.py', "reads past the trace's full-resolution region"),
         ('The valley note', P + 'raw_edit.py', 'The valley stands at'),
         ('The edge note', P + 'raw_edit.py', "sigma from the apex, under the method's"),
         ('Most calibrators dropped', P + 'method_profile_sections.py', 'Most calibrators dropped'),
         ('Submit and release wait for the run to be processed', P + 'raw_edit.py', 'Edits are waiting for the run to be processed again.'),
         ('The Manual changes panel', P + 'browser/templates/data_review.pt', 'Manual changes'),
         ('The verifier is never the analyst or an editor', P + 'manual_integration.py', 'a different person countersigns these manual changes'),
         ('A deleted qualifier is N.C. whatever the S/N rule', W + 'run_queue.py', 'for flag in qualifier_deleted_check(rows, analyte):'),
         ('A qualifier edit beside no quantifier peak is refused', P + 'raw_edit.py', 'a qualifier edit would have no effect.'),
         ('An edit with no effect asks nothing', P + 'manual_integration.py', 'less those the run could not apply'),
         ('Sign rights from People & Roles', P + 'manual_integration.py', 'sign right in People & Roles, so does not'),
         ('The countersign is saved once verified', P + 'browser/data_review.py', 'self._countersign_raw_changes(ws, save=True)'),
         ('An edit with no record holds the release', P + 'manual_integration.py', 'an edit has no record; undo it on the Raw Data tab'),
     ]},
    {"id": "spike-levels", "term": "Spike levels",
     "text": "The concentration a spiked QC sample is fortified at, per level (Low, "
             "Mid, High) and matrix, in that matrix's reporting unit (soil in ng/g, "
             "water in ng/L). Each spike in an extraction batch is given a level; its "
             "amount is the level's unless the bench records what was added. LFSMD "
             "uses its LFSM's. Without a level, recovery is not judged and the release "
             "is held.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("Read for each spiked injection", W + "method_profiles.py", "def resolve_spike"),
     ]},
    {"id": "sequence-export", "term": "Injection list",
     "text": "The built run as the file the instrument software imports (Waters "
             "MassLynx), kept per instrument in Import Studio beside its import "
             "mapping. Each column is filled with the injection name, description, "
             "vial, injection type, level, or a fixed text such as the MS or inlet "
             "method file; the injection type is written in the LIMS's words or "
             "MassLynx's (Analyte / Standard / QC / Blank), chosen on its row. Until an instrument has one saved, the MassLynx starter is "
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
     "where": [("QC criteria tab", "@@pfas-method-profiles"), ("Run Builder", "@@pfas-run-builder")],
     "who": "bench",
     "effects": [
         ("Decided", P + "run_plan.py", "def curve_decision"),
         ("Opening checks", P + "run_plan.py", "def opening"),
     ]},
    {"id": "calibration-curve", "term": "Calibration curve",
     "text": "Each analyte's response ratio, its peak area divided by its internal "
             "standard's, fitted against the expected concentration of each calibration level.",
     "where": [("Calibration Archive", "@@pfas-calibrations")],
     "who": "config",
     "effects": [
         ("The curve drawn and judged on the Calibration Archive", P + "browser/static/calibration_fit.js",
          "function fit(pts, opts)"),
         ("A manager's choice of fit, weighting and origin for one curve", P + "browser/calibrations.py",
          "def _handle_override(self):"),
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
    {"id": "chart-overlay", "term": "Control chart overlay",
     "text": "Plots a room's humidity or temperature, or a fridge's or freezer's temperature, "
             "on a second axis against the chart's runs: each run takes the mean of that day's "
             "readings from the unit's sensor. A drift in the QC results that follows the room "
             "points to the environment rather than the method. Days without readings are left "
             "blank.",
     "where": [("Control Charts", "@@pfas-control-chart")],
     "who": "bench",
     "effects": [
         ("Each run's reading", P + "browser/controlchart.py", "def overlay_series"),
         ("The day's mean", P + "facility_qc.py", "def daily_means"),
     ]},
    {"id": "project-qapp", "term": "Project QAPP",
     "text": "The quality assurance project plan a project's work follows. A QAPP belongs to "
             "one client but can be reused by other projects, so the list is not filtered by "
             "the client chosen. None means the work follows the laboratory's internal "
             "quality system.",
     "where": [("Projects", "@@pfas-projects")],
     "who": "config",
     "effects": [
         ("The QAPP list", P + "browser/projects.py", "def _list_qapp_docs"),
     ]},
    {"id": "calibration-levels", "term": "Calibration levels",
     "text": "The method's calibration ladder, in ng/mL in the extract or ppt in the "
             "sample. Its lowest level gives each analyte's RL unless one is typed (an "
             "ng/mL level is multiplied by the matrix factor), and it suggests the spike "
             "levels. An analyte calibrated over another range has a multiple of the "
             "ladder up to its highest standard.",
     "where": [("Analytes tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("The derived RL", P + "calibration_levels.py", "def derived_rl"),
     ]},
    {"id": "eis-limits", "term": "Surrogate (EIS) recovery limits",
     "text": "For a method whose Engine turns them on (EPA 1633A): the recovery "
             "window per SUR standard, for aqueous samples and per matrix class. A class "
             "limit overrides the aqueous one for that class; a blank class cell uses "
             "the aqueous limit. A class set to None is not assessed: its cell reads "
             "\u2717, and the certificate says Not assessed, which differs from No "
             "criterion set (no window at all).",
     "where": [("Isotope standards tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("One grid, stored per isotope standard", P + "method_profile_sections.py", "def read_eis_grid"),
         ("A class set to None", P + "profile_grids.py", "NOT_ASSESSED_WORDS = \"Not assessed for {0}\""),
         ("The certificate says Not assessed", P + "coa_qc_standards.py", "\"not assessed\": \"Not assessed\""),
     ]},
    # ── Publishing and documents ──────────────────────────────────────────
    {"id": "reporting-template", "term": "Reporting template revision",
     "text": "The controlled version of the certificate: its settings, the per-method "
             "certificate formats and its certificate layout (Document Templates), "
             "issued together by a manager. No certificate is published until a "
             "revision with a certificate layout is issued; a draft layout does not "
             "count. A later change shows as an unissued change until the next one is "
             "issued.",
     "where": [("Reporting Template", "@@pfas-report-template")],
     "who": "config",
     "effects": [
         ("Publishing waits for the first revision", P + "browser/guards.py", "class ReportTemplateGuard"),
         ("And for an issued certificate layout", P + "browser/guards.py", "class CertificateLayoutGuard"),
         ("No certificate stored without one", P + "browser/coa_storage.py", "raise DesignedCertificateError(LAYOUT_NEEDED)"),
         ("No sample's report in another template", P + "browser/coa_storage.py", "raise DesignedCertificateError(OTHER_TEMPLATE"),
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
             "identified method, no issued reporting template, no issued certificate "
             "layout, no laboratory address, or a run whose "
             "surrogate / internal-standard verdicts are missing, unrounded or judged "
             "under another rule. A sample with no run at all is not held.",
     "where": [("Data Review", "@@pfas-data-review"), ("Reporting Template", "@@pfas-report-template")],
     "who": "system",
     "lists": ["publish_holds"],
     "effects": [
         ("Method identified", P + "browser/guards.py", "class SampleMethodGuard"),
         ("Reporting template issued", P + "browser/guards.py", "class ReportTemplateGuard"),
         ("Certificate layout issued", P + "browser/guards.py", "class CertificateLayoutGuard"),
         ("Laboratory address set", P + "browser/guards.py", "class LabAddressGuard"),
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
     "text": "Who signs as preparer, reviewer or both, set per person on People & Roles "
             "with their title, credentials and signature. A designed document that "
             "places a signature its signer may not give is refused.",
     "where": [("People & Roles", "@@pfas-people"), ("My profile", "@@pfas-my-profile")],
     "who": "config",
     "effects": [
         ("Certificate signatories checked", P + "browser/coa_document.py", "may not sign as"),
         ("Extraction log, QC Review and logbook signatories", P + "browser/doc_people.py", "class SignatoryError"),
     ]},
    {"id": "lab-director", "term": "Laboratory Director",
     "text": "The one person named on the Laboratory page whose name and signature appear as "
             "Director on designed documents.",
     "where": [("Laboratory", "@@pfas-laboratory")],
     "who": "config",
     "effects": [
         ("Read for every designed document", P + "browser/staff.py", "def director_userid"),
     ]},
    {"id": "laboratory-page", "term": "Laboratory",
     "text": "The laboratory's name, addresses, accreditation, logo and Director, kept as "
             "SENAITE's own Laboratory record so SENAITE and the add-on never disagree. The name "
             "is the browser tab title and the sign-in page heading; the logo, uploaded here, is the site logo. "
             "Only a Lab Manager or a site administrator saves it; a Lab Clerk "
             "cannot edit the Laboratory. A certificate already issued keeps the identity it "
             "was issued with.",
     "where": [("Laboratory", "@@pfas-laboratory")],
     "who": "config",
     "effects": [
         ("The Director is SENAITE's Laboratory Supervisor", P + "lab_identity.py", "def set_supervisor"),
         ("Every change recorded in Configuration History", P + "lab_identity.py", "def save(portal, values"),
     ]},
    {"id": "people-roles", "term": "People and roles",
     "text": "Each person's sign-in, Lab Contact, roles, badge and e-mail. A Lab Manager changes "
             "another person's roles with a reason, never their own, and never on an "
             "administrator's account; only a site administrator takes the Lab Manager role away "
             "or changes a Lab Manager's e-mail or password reset. Deactivating a person needs a "
             "reason: their account leaves every role group, their badge is revoked, and the "
             "account stays for the audit trail. "
             "Pickers list only active people with a sign-in. Every change is recorded in "
             "Configuration History.",
     "where": [("People & Roles", "@@pfas-people"), ("Configuration History", "@@pfas-config-history")],
     "who": "config",
     "effects": [
         ("Only a Site Administrator removes the Lab Manager role", P + "role_guard.py",
          "Only a Site Administrator takes the Lab Manager role away."),
         ("Accounts managed only within these limits", P + "role_guard.py", "def may_manage_account"),
         ("The reset e-mail sent under a narrow elevation", P + "role_guard.py", "def send_reset"),
     ]},
    {"id": "time-language", "term": "Time and language",
     "text": "The site language and the laboratory time zone, which is Plone's own setting. Every "
             "time the system shows, prints or reads follows that one zone: a time you type is "
             "read in it, and a date with no time is never moved. Printed documents say once "
             "which zone their times are in. Stored records are not changed. Both settings are "
             "checked before either is saved, so a refusal changes neither.",
     "where": [("Time & Language", "@@pfas-time-language")],
     "who": "config",
     "effects": [
         ("A zone not on the list is refused", P + "browser/time_language.py", "def _zone_ok"),
         ("The change is recorded", P + "browser/time_language.py", "Laboratory time zone"),
     ]},
    {"id": "system-page", "term": "System",
     "text": "Notice reminders and the raw-data share, with links to Plone's own mail, security "
             "and site panels, which only a site administrator sees. The raw-data share is "
             "saved by a site administrator only.",
     "where": [("System", "@@pfas-system")],
     "who": "site_admin",
     "effects": [
         ("The share saved with its change recorded", P + "browser/system_settings.py", "def _save_raw"),
     ]},
    {"id": "backups", "term": "Backups",
     "text": "Every backup is encrypted to the Director's and the QAO's keys, kept offline: "
             "the server can make backups but not read them. A full install backup can rebuild "
             "the whole system; a full backup each quarter and a daily increment between keep "
             "any day of the last 90 and every quarter for 5 years. A key holder restores a "
             "backup into a test system once a quarter. One method's configuration can be "
             "restored on its own: its changes are shown first and recorded in Configuration "
             "History with the reason. Status is the backup tool's own report after each run. "
             "Backup settings are changed here by a site administrator, with a reason: the "
             "destination, when backups run, when old ones are removed and the public keys; each "
             "change waits for the tool's next run, which applies it or refuses it (a destination "
             "must be mounted and writable; at least two public keys, no private key) and says so "
             "under Settings changes. A waiting change can be withdrawn. Backups already made stay "
             "readable only with the keys they were made with.",
     "where": [("Backups", "@@pfas-backups"), ("Configuration History", "@@pfas-config-history")],
     "who": "config",
     "effects": [
         ("A failed backup or a restore test due on the Manager's landing", P + "attention.py", "Restore test due"),
         ("A method restore through each store's tracked saver", P + "method_restore.py", "def apply"),
         ("Settings changes, applied by the tool at its next run", P + "backup_settings.py", "def request("),
     ]},
    {"id": "badges", "term": "Badges and lab terminals",
     "text": "At a registered lab terminal a badge scan signs its holder in (and "
             "switches user); the terminal signs out after 10 minutes without "
             "activity. Administrators always use their password.",
     "where": [("Lab terminals", "@@pfas-terminals"), ("People & Roles", "@@pfas-people")],
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
    {"id": "edd-column-mapped", "term": "Column-mapped EDD profiles",
     "text": "A delivery format described on the EDD pages, never in code. Files: each file's name "
             "with the SDG, batch and date inserted as chips, its rows (one per sample, per result, or per "
             "test and lab batch), delimiter, header row (plain, a comment row with its prefix, or "
             "none) and line ending; several files are delivered as one zip. Columns: each column's "
             "heading, the platform fact it carries (or a constant, or nothing), a fact to use when "
             "that one is blank, a code map, a format (date:%m/%d/%Y %H:%M, cas:dashed, cas:digits, "
             "upper, lower), when it is written (a fact; not a fact; a fact = a value, != a value, in "
             "a,b or not in a,b), how a list of codes is joined, and whether it is required, from a "
             "value list, or of a maximum length. Code maps: our value to the format's code; a map "
             "keyed by a second fact looks up \"value|second\" first (e.g. Drinking Water|FB). A value "
             "a map lacks, a blank required field, a code outside its list and a profile's own "
             "problem block the delivery. Value lists: one column of a sheet of the agency's "
             "workbook, or pasted codes. Lab values: the lab's identity, named for the columns (the "
             "sample delivery group follows the prefix and format values). Client fields: what a "
             "client gives, on its EDD settings for any profile. The profile is chosen per export "
             "on the batch EDD page; a profile no client uses can be deleted.",
     "where": [("EDD Export", "@@pfas-edd-config")],
     "who": "config",
     "effects": [
         ("A value a map lacks is refused", P + "edd_delimited.py", "def lookup"),
         ("A profile's own problems block the delivery", P + "edd_delimited.py", "def problems"),
         ("The profile chosen for an export", P + "edd_store.py", "def get_edd_profile_for_client"),
         ("Deleted only when no client uses it", P + "edd_store.py", "def delete_edd_profile"),
     ]},
    {"id": "import-profiles", "term": "Import layouts",
     "text": "How an instrument export is laid out and what its columns mean, saved by name "
             "in Import Studio. The reader options (delimiter, encoding, header row, "
             "missing-value markers, rows to skip; a long table, column groups per compound "
             "on two header rows, or one block per compound) are form controls; the studio "
             "and the worker read a file with them in the same way. A file is matched to the "
             "active layout it fits best: by default the columns of the fields the layout "
             "needs (injection, compound, a result, any it marks required) must be found, "
             "compared without case, spacing, punctuation or a unit in brackets, and other "
             "columns may be added or left out; a layout set to \"exactly these columns\" "
             "asks for the same columns. The run's instrument ranks first, then the most "
             "columns matched. A tie is refused naming both layouts; a file no layout fits "
             "is refused naming each missing column and the nearest headers, and is mapped "
             "in Import Studio from what was found, never guessed. A layout bound to an instrument is "
             "used only for its runs. A retired layout is never used; a deleted one is kept "
             "in Configuration History. Words the export uses for the platform's are mapped "
             "one per line (field: export's word = platform's), scales one per line "
             "(field = factor, or percent); a row named compound + the qualifier suffix is "
             "that compound's qualifier transition.",
     "where": [("Import Studio", "@@pfas-import-studio")],
     "who": "config",
     "effects": [
         ("The pipeline reads only saved mappings", W + "importer.py", "column mapping saved in Import Studio"),
         ("A file is matched to one layout, else refused", P + "import_layouts.py", "def match"),
         ("An export no row of which can be read is refused", W + "pipeline.py", "def refuse_unreadable"),
     ]},
    # ── Projects ──────────────────────────────────────────────────────────
    {"id": "project-specs", "term": "Project specs",
     "text": "A project's differences from its method (added analytes, reporting "
             "limits, recovery windows, RPD limits, isotope standards). Batches linked "
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
    {"id": "pipette-quarter", "term": "Pipette calibration due",
     "text": "One calibration in each calendar quarter: a calibration in Q4 2026 makes the "
             "next due in Q1 2027, by its last day. An external calibration is due when its "
             "certificate says.",
     "where": [("Pipettes", "@@pfas-pipette-calibration")],
     "who": "bench",
     "effects": [
         ("The quarter's last day", P + "facility_qc.py", "def quarter_due(cal_date)"),
     ]},
    {"id": "sensor-key", "term": "Sensor key",
     "text": "One key for the whole laboratory. Each Raspberry Pi sends it with every "
             "reading, together with its sensor ID, the time, the temperature and the "
             "humidity. The sensor ID is matched to the instrument whose Equipment settings "
             "hold it, and the reading goes into that instrument's temperature log, judged "
             "against its own range. Equipment Checks shows it.",
     "where": [("Equipment Types", "@@pfas-equipment-types")],
     "who": "config",
     "effects": [
         ("The key is checked", P + "browser/facility_qc.py", "expected_key = db.get_api_key("),
         ("The sensor finds its instrument", P + "browser/equipment.py", "def get_unit_by_sensor(sensor_id)"),
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
             "when it is made. A composite states how many items were composited: separate items, such as "
             "eggs, fish or portions, ground together into this one sample. "
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
             "takes the test portion is the Sample Processing Log. An extraction keeps the "
             "stages and method revision it started with, so a later change to the method's "
             "stages never moves its records. A stage that creates a solution records a new "
             "in-house Prepared Standard lot, its parents the stage's reagents and its expiry "
             "the tightest of theirs; a stage that captures the standard pedigree records which "
             "prepared-standard lots were spiked, the link Data Review's traceability check reads.",
     "where": [("Run & reporting tab", "@@pfas-method-profiles"), ("Extraction Guide", "@@pfas-extraction-guide")],
     "who": "bench",
     "effects": [
         ("Stages from the plan the extraction started with, else the method profile", P + "stage_plan.py", "def stages_for(session, profile)"),
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
    # ── Pages and grids ───────────────────────────────────────────────────
    {"id": "navigation", "term": "Finding and pinning pages",
     "text": "The dark rail down the left edge has Home and one button for each section of the "
             "laboratory's work. A section's button shows its pages in the panel beside the rail, "
             "as a tree: a row with a small arrow holds the pages beneath it, and the row of the "
             "page you are on is marked. Home shows the Dashboard and the pages you pinned. To "
             "pin a page, open its row's menu and choose Pin; the same menu opens a page in a new tab. "
             "With a mouse, the menu button at the end of the row opens it; from the keyboard, "
             "select the row and press Shift+F10 or the menu key. "
             "You can pin 20 pages. The menu button in the top bar folds the panel away on a "
             "wide screen; on a smaller screen the panel stays folded and a tap on the rail "
             "opens it over the page. On a phone the rail is a bar along the bottom and a tap "
             "opens the section as a sheet. The search box at the top finds every page in the "
             "panel by its name; press / to go to it. You see only the pages your role may open.",
     "where": [("Home", "@@pfas-home")],
     "who": "system",
     "effects": [
         ("The rail and the tree are drawn from one list of pages", P + "page_groups.py", "def nav_model("),
         ("The row menu opens from the keyboard", P + "browser/static/pfas-components.js", "e.shiftKey && e.key === \"F10\""),
         ("The panel folds by the width of the screen", P + "browser/static/pfas-sidebar.js", "nav.mode = function"),
         ("At most 20 pins", P + "browser/sidebar_pins.py", "MAX_PINS = 20"),
     ]},
    {"id": "column-chips", "term": "Column chips and wide grids",
     "text": "A grid wider than its frame scrolls sideways inside its own box: its first "
             "column stays pinned and a chip at the top right counts the columns out of "
             "view (\"3 more \u2192\"); a click on the chip shows the next ones. While a "
             "table's own scrollbar is below the window, a scrollbar pinned to the bottom "
             "of the window scrolls it, and the wheel over that bar scrolls sideways. On a "
             "computer, press the mouse wheel over a table and move the pointer: the table "
             "scrolls that way, faster the further it moves; a click or Esc stops it. "
             "Shift with the wheel also scrolls sideways. The chips above "
             "the grid name the columns shown: remove one with its \u00d7, and the last chip "
             "adds back the hidden ones. On a computer a column widens by dragging the edge "
             "of its heading; this browser remembers the widths for each grid. Nothing "
             "about the columns is saved with the method.",
     "where": [("Method Profiles", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("The chips above a grid", P + "profile_grids.py", "def _tools(sheet)"),
         ("Widths remembered in this browser", P + "browser/static/pfas-components.js",
          "function initColResize(table, key)"),
         ("The count of columns out of view", P + "browser/static/pfas-components.js",
          "function initScrollCue(wrap)"),
     ]},
    {"id": "folded-groups", "term": "Folded groups",
     "text": "In a grid whose rows inherit from a group, a group whose members all hold "
             "the group's value folds to one row stating the value and a count (\"20 "
             "analytes \u00b7 all 40 \u2013 130\"). A group with a difference names it on "
             "the row and opens to show its members: a value set on the member in full "
             "weight with the teal edge, the others muted. The grid opens with every "
             "group folded, and this browser remembers which you opened, per method and "
             "QC type shown. A folded member still saves with the tab.",
     "where": [("QC criteria tab", "@@pfas-method-profiles")],
     "who": "config",
     "effects": [
         ("The folded row says what its members hold", P + "profile_grids.py",
          "def group_summary(members, columns, group=None)"),
         ("The open groups, kept per method and tab", P + "browser/static/method_profile_edit.js",
          "\"pfas.mp.grp.\""),
     ]},
    {"id": "help-panel", "term": "The Help panel",
     "text": "Each section header ends in one Help button. It opens that section's entry "
             "in a panel beside the page, which stays open while you work; the entry ends "
             "with buttons to the entries related to it, which open in the same panel, and "
             "Open in Help shows it on its tab of this page. Nothing on a page takes the "
             "focus when it loads, so the first key you press acts where you choose.",
     "where": [("Method Profiles", "@@pfas-method-profiles"), ("Run Builder", "@@pfas-run-builder")],
     "who": "bench",
     "effects": [
         ("A Help button opens its entry beside the page", P + "browser/static/pfas-components.js",
          "function openHelp(btn)"),
         ("The panel, drawn once by the page frame", P + "browser/templates/pfas_macros.pt",
          "<aside class=\"pfas-help-panel\""),
         ("The button every section's header ends in", P + "help_dictionary.py", "def help_button(entry_id)"),
     ]},
    # ── Review: the warnings ──────────────────────────────────────────────
    {"id": "warnings-strip", "term": "The warnings strip",
     "text": "Data Review's warnings are one strip under the title: the count of items "
             "that block release, in coral, and the count of notes, muted. It is open on "
             "the Overview and folded on the other tabs. Opened, it is a table with a "
             "Severity column, blocks first, and a Fix button on each row that opens the "
             "page where the fix is made. Blocks means the item holds the QC gate or the "
             "release; the QC Summary verdict and the Blanks verdict read the same gate, "
             "so the strip, the card and the tab never disagree. A worksheet with no "
             "imported run shows one blocks row saying so.",
     "where": [("Data Review", "@@pfas-data-review")],
     "who": "bench",
     "effects": [
         ("The rows and their severity", P + "browser/data_review.py", "def warnings(self)"),
         ("One reading of the QC gate", P + "browser/data_review.py", "def _qc_gate(self, summary)"),
         ("A worksheet with no run", P + "browser/data_review.py", "No run imported yet."),
     ]},
    # ── Reporting: the J and D qualifiers ─────────────────────────────────
    {"id": "qualifier-j", "term": "Estimated value (J)",
     "text": "A result at or above the MDL and below the RL prints its value with the "
             "qualifier J: detected, the value an estimate. A result below the MDL prints "
             "as a non-detect with U; without an MDL no J is possible and the MDL cell "
             "prints \u2014. The MDL of a diluted result is scaled by the dilution, as its RL "
             "is. Certificate format sets the rule per method and matrix (J, or \"< RL\" "
             "as before) and QC Qualifiers holds its wording. A certificate prints as its "
             "reporting-template revision was issued: a revision issued before J existed "
             "prints \"< RL\" until a new one is issued.",
     "where": [("Run & reporting tab", "@@pfas-method-profiles"), ("QC Qualifiers", "@@pfas-qc-qualifiers")],
     "who": "config",
     "effects": [
         ("Printed between the MDL and the RL", P + "coa_format.py", "J_CODE = \"J\""),
         ("The rule on Certificate format", P + "report_format.py", "\"Between MDL and RL\""),
         ("Older revisions keep their rule", P + "report_format.py", "LEGACY_DEFAULTS = {"),
     ]},
    {"id": "qualifier-d", "term": "Diluted (D)",
     "text": "A result from a diluted analysis (a dilution above 1:1) carries D. Its row keeps its "
             "own date of analysis with a footnote mark, and the footnote under the table "
             "gives the dilution and the date and time (\"Re-analysed at a 1:5 dilution on "
             "2026-10-07 09:12\"). Its RL and MDL are the method's times the dilution. A "
             "re-injection at no dilution keeps its own date of analysis and carries no D. A "
             "revision issued before D existed prints none. The EDD carries the dilution in "
             "its dilution factor, not as D; a D the lab's own QC qualifiers give still "
             "reaches it.",
     "where": [("Data Review", "@@pfas-data-review"), ("Reporting Template", "@@pfas-report-template")],
     "who": "system",
     "effects": [
         ("Given to a diluted result", P + "coa_format.py", "D_CODE = \"D\""),
         ("The footnote under the table", P + "coa_document.py", "def dilution_notes(rows)"),
         ("Left out of the EDD", P + "edd_builder.py", "DILUTION_CODE = \"D\""),
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


def term_of(entry_id):
    """The entry's term, as a Help button names it; an unknown id is itself."""
    e = entry(entry_id)
    return e["term"] if e else entry_id


def related(entry_id):
    """[(id, term)] of the entries RELATED names for this one."""
    return [(r, term_of(r)) for r in RELATED.get(entry_id, ())]


def help_button(entry_id):
    """The Help control for one entry, as the page macro "help" draws it:
    a button that opens the entry in the panel beside the page."""
    return (u'<button type="button" class="btn-help" data-help-entry="{0}" aria-label="Help: {1}" '
            u'aria-haspopup="dialog">?</button>').format(escape(entry_id), escape(term_of(entry_id)))


def escape(text):
    """Text made safe in markup and in an attribute value, either quote."""
    return _escape(u"%s" % text)


def grouped():
    """[(group, [entries])] in GROUPS order, each tab in its listed order."""
    by_id = dict((e["id"], e) for e in ENTRIES)
    return [(g, [by_id[i] for i in _TAB[g] if i in by_id]) for g in GROUPS]

