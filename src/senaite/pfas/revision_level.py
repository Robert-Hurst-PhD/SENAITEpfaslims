# -*- coding: utf-8 -*-
"""The level of a method revision: what changed since the last issued one.

A revision number is major.sub. Issuing compares the method's settings with
the last issued revision's snapshot (method_revisions.snapshot_of: the
profile as the fingerprint reads it, and the rule switches) and the level
follows from what changed:

    major   the analytes and panels, the QC types and their criteria, or
            the calculation and reporting (4.1 to 5.0);
    sub     anything else, every integration setting included (4.0 to 4.1).

Each top-level profile key belongs to one group; `integration` is split by
path, a compound's transitions, peak mode and partner being its analytes and
its expected ion ratio a QC criterion. A key in neither MAJOR nor SUB is
major: an unclassified change never issues as a sub. The rule switches are a
QC criterion. No snapshot of the last revision is major. The keys the system
keeps for itself (HOUSEKEEPING) are never compared; when they alone moved,
the revision is a sub named "Housekeeping".

Pure, standard library only. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

MAJOR_LEVEL, SUB_LEVEL = "major", "sub"

# the group words a revision names as what changed
ANALYTES = u"Analytes and panels"
QC = u"QC types and criteria"
CALC = u"Calculation and reporting"
INTEGRATION = u"Integration"
NAMES = u"Names and codes"
STAGES = u"Extraction stages"
PRINTING = u"Print settings"
WORKFLOW = u"Bench workflow"
OTHER = u"Other settings"
HOUSEKEEPING_WORD = u"Housekeeping"
NO_SNAPSHOT = u"no snapshot of the last revision"

_ANALYTE_KEYS = ("master_analyte_set", "display_analyte_set", "analyte_matrix_inclusion",
                 "supported_matrices", "labelled_standards", "surrogate_map", "composite_standards",
                 "isomers", "key_analytes",
                 # derived from the matrices: it moves with them
                 "matrix_uid_map")
# which QC types run and how often (the run template, the required studies,
# the worksheet size), and every acceptance limit or window: receipt and
# storage temperatures and holding times decide whether a sample is accepted
_QC_KEYS = ("qc_acceptance", "rule_states", "rule_toggles", "limit_states", "spike_levels",
            "instrument_verification", "eis_overrides", "eis_matrix_overrides", "idc",
            "surrogate_failure_scope", "matrix_classes", "run_template", "study_kinds", "extraction_batch",
            "holding_times", "processed_holding_times", "extract_holding_times", "sample_holding_none",
            "receipt_temperature", "storage_temperature", "storage_temperature_processed",
            "storage_temperature_extract", "receipt_temperature_by_matrix", "storage_temperature_by_matrix",
            "storage_temperature_processed_by_matrix", "storage_temperature_extract_by_matrix",
            "dilution_recovery", "mxb_reference_recovery")
# what a reported value is computed or reported with
_CALC_KEYS = ("engine", "unit_map", "units", "matrix_factors", "salt_adjustment_factors",
              "nominal_amounts", "reporting_limits", "report_format", "regulatory_limits", "dilution",
              "sample_correction", "blank_subtraction", "spike_basis", "linked_response_ratio",
              "weight_basis_map", "tight_matrices")

# {profile key: group} of a change that makes a major revision
MAJOR = dict([(k, ANALYTES) for k in _ANALYTE_KEYS] + [(k, QC) for k in _QC_KEYS]
             + [(k, CALC) for k in _CALC_KEYS])
# {profile key: group} of a change that makes a sub revision; `integration`
# is sub but for INTEGRATION_MAJOR's paths
SUB = {"integration": INTEGRATION, "display_name": NAMES, "description": NAMES,
       "extraction_stages": STAGES, "matrix_codes": NAMES, "matrix_aliases": NAMES,
       "qc_name_codes": NAMES, "blank_role_name": NAMES, "print_settings": PRINTING,
       "method_codes": NAMES, "extraction_labels": WORKFLOW, "solvent_channels": WORKFLOW}
# keys the system keeps, never a setting: the seeding mark, the method's own
# id and the panel links' schema stamp. Never compared as a change; when
# they alone moved the fingerprint, the revision is a sub, "Housekeeping"
HOUSEKEEPING = ("_seeded", "method_id", "analyte_links_v")
# a compound's own Integration entry (integration.analytes.<keyword>.<key>)
# that is not an integration setting
INTEGRATION_MAJOR = {"quant": ANALYTES, "quals": ANALYTES, "mode": ANALYTES, "partner": ANALYTES,
                     "expected_ion_ratio": QC}


def classify(path):
    """(level, group) of one changed path of a snapshot: ("toggles", ...)
    or ("profile", key, ...)."""
    if not path or path[0] == "toggles":
        return MAJOR_LEVEL, QC
    key = path[1] if len(path) > 1 else None
    if key == "integration":
        if len(path) > 4 and path[2] == "analytes" and path[4] in INTEGRATION_MAJOR:
            return MAJOR_LEVEL, INTEGRATION_MAJOR[path[4]]
        return SUB_LEVEL, INTEGRATION
    if key in MAJOR:
        return MAJOR_LEVEL, MAJOR[key]
    if key in SUB:
        return SUB_LEVEL, SUB[key]
    return MAJOR_LEVEL, OTHER


def _leaves(changes):
    """config_history.diff stops where one side has no value: a compound's
    whole row added is one change at the row. Each such change is split to
    the paths under it, so a row is graded by what it holds."""
    from senaite.pfas import config_history
    out = []
    for path, before, after in changes:
        if isinstance(before, dict) or isinstance(after, dict):
            # a non-empty path: the history's top-level skips do not apply
            inner = config_history.diff(before if isinstance(before, dict) else {},
                                        after if isinstance(after, dict) else {}, tuple(path))
            if inner:
                out += _leaves(inner)
                continue
        out.append((tuple(path), before, after))
    return out


def changed_paths(before, after):
    """Every changed path between two snapshots, each under "profile" or
    "toggles". Compared below the top level, so a key the change history
    leaves out (the panel's display set) is still compared."""
    from senaite.pfas import config_history

    def wrap(snap):
        profile = dict((k, v) for k, v in ((snap or {}).get("profile") or {}).items() if k not in HOUSEKEEPING)
        return {"profile": profile, "toggles": (snap or {}).get("toggles") or {}}
    return [p for p, _b, _a in _leaves(config_history.diff(wrap(before), wrap(after)))]


def _housekeeping_moved(before, after):
    b, a = (before or {}).get("profile") or {}, (after or {}).get("profile") or {}
    return any(b.get(k) != a.get(k) for k in HOUSEKEEPING)


def level(before, after):
    """(level, groups): "major", "sub" or None when nothing changed, and the
    sorted group words of what changed. `before` None, no snapshot of the
    last revision: major."""
    if before is None:
        return MAJOR_LEVEL, [NO_SNAPSHOT]
    found = [classify(p) for p in changed_paths(before, after)]
    if not found:
        return (SUB_LEVEL, [HOUSEKEEPING_WORD]) if _housekeeping_moved(before, after) else (None, [])
    lvl = MAJOR_LEVEL if any(l == MAJOR_LEVEL for l, _g in found) else SUB_LEVEL
    return lvl, sorted(set(g for _l, g in found))


def why(groups):
    """What a revision says of its level: "Integration changed", "no
    snapshot of the last revision", or u"" (the first revision)."""
    groups = list(groups or [])
    if not groups:
        return u""
    if groups == [NO_SNAPSHOT]:
        return NO_SNAPSHOT
    return u"%s changed" % u", ".join(groups)


def sentence(preview):
    """The Issue dialog's line: "Issues revision 4.1: Integration changed.";
    "Level not known." when the preview could not be made."""
    if not preview.get("label"):
        return u"Level not known."
    reason = why(preview.get("groups"))
    return (u"Issues revision %s: %s." % (preview.get("label"), reason) if reason
            else u"Issues revision %s." % preview.get("label"))
