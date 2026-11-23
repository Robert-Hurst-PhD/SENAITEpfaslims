# -*- coding: utf-8 -*-
"""Certificate format per method x matrix.

The certificate settings live on each method profile, with an "All matrices"
row and optional per-matrix rows; a blank cell inherits:

    matrix row  ->  "All matrices" row  ->  built-in default

    report_format = {"*": {setting: value}, "<matrix title>": {setting: value}}

Print Settings keeps what is lab-wide (header, footer, sign-off).

A matrix row may also hold `limits_off`: the ids of regulatory limits (action
levels, MCLs -- values kept centrally on Regulatory Limits) that this method's
certificates do NOT evaluate for that matrix. Only exclusions are stored, so
every limit naming the matrix applies unless switched off here. Pure; Py2.7.
"""
from __future__ import absolute_import, unicode_literals

# the surrogate / internal-standard note's default, drafted from
# the lab's words; kept here so this module imports nothing (the worker loads
# it by path: pfas_pipeline.addon)
QC_NOTE = ("Quality control data specific to this sample: labelled surrogate and "
           "internal standards, used to account for sample concentrations or to "
           "verify recovery efficiencies. They are not reported results.")

KEY = "report_format"
ALL = "*"

YES_NO = [("yes", "Show"), ("no", "Hide")]
# (key, label, choices, built-in default). Booleans are stored "yes"/"no" so a
# per-matrix cell can be blank (= inherit) rather than forced to a value.
SETTINGS = [
    ("coa_show_cas", "CAS column", YES_NO, "yes"),
    ("coa_show_mdl", "MDL column", YES_NO, "yes"),
    ("coa_show_dilution", "Dilution column", YES_NO, "no"),
    ("coa_nd_format", "Non-detects print as",
     [("lt_rl", "< RL, U"), ("nd", "ND, U"), ("raw", "As stored")], "lt_rl"),
    # a value at or above the MDL and below the RL (coa_format); with no MDL
    # set no J is possible
    ("coa_between_mdl_rl", "Between MDL and RL",
     [("j", "Value with J"), ("lt_rl", "< RL with U")], "j"),
    ("coa_sig_figs", "Significant figures", [("2", "2"), ("3", "3"), ("4", "4")], "3"),
    # results, RL and MDL (rounding.py). Built-in default = round half up.
    ("coa_rounding", "Rounding rule",
     [("epa", "EPA: round half up"), ("fda", "FDA: round half up"),
      ("iso", "ISO: round half to even (ISO 80000-1)")], "epa"),
    ("coa_show_regulatory", "Regulatory-limit notes", YES_NO, "yes"),
    ("coa_note", "Standard note", None, ""),
    # under the surrogate / internal-standard sub-table; the
    # default is drafted from the lab's words
    ("coa_qc_note", "Surrogate / internal-standard note", None, QC_NOTE),
]
BOOLEAN = set(k for k, _l, c, _d in SETTINGS if c is YES_NO)
# A reporting-template revision prints as it did when issued. A setting added
# after revisions were first issued reads, for a revision that does not record
# it, the rule in force before it existed; a revision records the built-in
# default of each of these (report_templates.snapshot).
# Rules the code applies, not settings the lab sets, recorded the same way:
# coa_mdl_dilution "yes" = a diluted result's MDL scales with the fold, as
# its RL does (printed, and for the J decision); coa_dilution_code "yes" = a
# diluted result carries D (and the legend its line); coa_legend_page "yes" =
# the key (the legend: every code's full wording) prints on a page of its
# own, nothing under the results table.
RULE_DEFAULTS = {"coa_mdl_dilution": "yes", "coa_dilution_code": "yes", "coa_legend_page": "yes"}
LEGACY_DEFAULTS = {"coa_between_mdl_rl": "lt_rl", "coa_mdl_dilution": "no", "coa_dilution_code": "no",
                   "coa_legend_page": "no"}


def recorded_defaults():
    """{setting or rule: built-in default} a revision records when issued."""
    out = dict((k, d) for k, _l, _c, d in SETTINGS if k in LEGACY_DEFAULTS)
    out.update(RULE_DEFAULTS)
    return out


def rules(defaults=None):
    """The code's rules a certificate prints by: an issued revision's
    (issued_defaults), else the current ones."""
    return dict((k, (defaults or {}).get(k, v)) for k, v in RULE_DEFAULTS.items())


def issued_defaults(recorded):
    """The defaults an issued revision prints with: what it recorded, else
    the rule in force before the setting existed."""
    out = dict(LEGACY_DEFAULTS)
    out.update(recorded or {})
    return out


def _stored(value, key):
    if key in BOOLEAN and isinstance(value, bool):
        return "yes" if value else "no"
    return "%s" % value if value is not None else None


LIMITS_OFF = "limits_off"


def limits_off(profile, matrix):
    return list(((((profile or {}).get(KEY) or {}).get(matrix) or {}).get(LIMITS_OFF)) or [])


def limit_applies(profile, matrix, limit_id):
    """Does this method's certificate evaluate the limit for this matrix?"""
    return limit_id not in limits_off(profile, matrix)


def set_limit(profile, matrix, limit_id, applies):
    """Switch one limit on/off for a method x matrix (in place). An empty
    exclusion list, and then an empty matrix row, are removed."""
    fmt = profile.setdefault(KEY, {})
    row = dict(fmt.get(matrix) or {})
    off = [x for x in (row.get(LIMITS_OFF) or []) if x != limit_id]
    if not applies:
        off.append(limit_id)
    if off:
        row[LIMITS_OFF] = sorted(off)
    else:
        row.pop(LIMITS_OFF, None)
    if row or matrix == ALL:
        fmt[matrix] = row
    else:
        fmt.pop(matrix, None)
    return profile


def resolve(profile, matrix, defaults=None):
    """The effective settings for one method x matrix, as the certificate
    reads them (booleans as True/False). `defaults` replaces a setting's
    built-in default (an issued revision's, issued_defaults)."""
    fmt = (profile or {}).get(KEY) or {}
    out = {}
    for key, _label, _choices, default in SETTINGS:
        value = (defaults or {}).get(key, default)
        for scope in (ALL, matrix):
            v = (fmt.get(scope) or {}).get(key)
            if v not in (None, ""):
                value = v
        out[key] = (value == "yes") if key in BOOLEAN else value
    return out
