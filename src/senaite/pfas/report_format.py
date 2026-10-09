# -*- coding: utf-8 -*-
"""Certificate format per method x matrix.

Lab: "The reporting page should be tied to each method as it changes by method
and matrix." The certificate settings that were one global block in Print
Settings live on each method profile, with an "All matrices" row and optional
per-matrix rows; a blank cell inherits:

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
    ("coa_sig_figs", "Significant figures", [("2", "2"), ("3", "3"), ("4", "4")], "3"),
    # results, RL and MDL (rounding.py; lab assignment 2026-10-05).
    # Built-in default = round half up, what certificates did before.
    ("coa_rounding", "Rounding rule",
     [("epa", "EPA: round half up"), ("fda", "FDA: round half up"),
      ("iso", "ISO: round half to even (ISO 80000-1)")], "epa"),
    ("coa_show_regulatory", "Regulatory-limit notes", YES_NO, "yes"),
    ("coa_note", "Standard note", None, ""),
    # under the surrogate / internal-standard sub-table; the
    # default is drafted from the lab's words of 2026-10-05
    ("coa_qc_note", "Surrogate / internal-standard note", None, QC_NOTE),
]
BOOLEAN = set(k for k, _l, c, _d in SETTINGS if c is YES_NO)
# the global Print Settings keys these came from (the migration's source)
LEGACY_KEYS = ("coa_show_cas", "coa_show_mdl", "coa_show_dilution", "coa_nd_format",
               "coa_sig_figs")


def _stored(value, key):
    if key in BOOLEAN and isinstance(value, bool):
        return "yes" if value else "no"
    return "%s" % value if value is not None else None


def from_print_settings(print_settings):
    """The "All matrices" row that reproduces today's global settings."""
    row = {}
    for key in LEGACY_KEYS:
        if key in (print_settings or {}):
            row[key] = _stored(print_settings[key], key)
    return {ALL: row}


def migrate(profile, print_settings):
    """True if `profile` gained its report_format (idempotent)."""
    if KEY in profile:
        return False
    profile[KEY] = from_print_settings(print_settings)
    return True


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


def resolve(profile, matrix):
    """The effective settings for one method x matrix, as the certificate
    reads them (booleans as True/False)."""
    fmt = (profile or {}).get(KEY) or {}
    out = {}
    for key, _label, _choices, default in SETTINGS:
        value = default
        for scope in (ALL, matrix):
            v = (fmt.get(scope) or {}).get(key)
            if v not in (None, ""):
                value = v
        out[key] = (value == "yes") if key in BOOLEAN else value
    return out
