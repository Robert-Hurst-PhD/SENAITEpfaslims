# -*- coding: utf-8 -*-
"""Certificate format per method x matrix (DECISIONS 2026-10-01).

Lab: "The reporting page should be tied to each method as it changes by method
and matrix." The certificate settings that were one global block in Print
Settings live on each method profile, with an "All matrices" row and optional
per-matrix rows; a blank cell inherits:

    matrix row  ->  "All matrices" row  ->  built-in default

    report_format = {"*": {setting: value}, "<matrix title>": {setting: value}}

Print Settings keeps what is lab-wide (header, footer, sign-off). Pure; Py2.7.
"""
from __future__ import absolute_import, unicode_literals

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
    ("coa_show_regulatory", "Regulatory-limit notes", YES_NO, "yes"),
    ("coa_note", "Standard note", None, ""),
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
