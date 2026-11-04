"""How a dilution's route decides what the worker judges on it.

A method allows its dilution routes (the add-on's Lab Workflow, Dilutions;
a project may override them), and each dilution recorded on FM-ENV-003
names its route. The surrogate (extracted internal standard) in a diluted
injection is judged only when it was added to the dilution -- the re-spike
route, or a dilution made with the surrogate added or topped up -- against
the method's window, the method's lowest EIS recovery in a diluted extract
(when set) as its low end. A dilution without the surrogate added is the
same extract with its surrogate diluted too, so its recovery is not judged.

`entry` is the dilution map's entry for the injection ({"parent", "factor",
"route", "sur_handling", ...}); `settings` is the profile's "dilution" dict.
"""
from __future__ import annotations

import dataclasses

ADDED = ("added", "topped_up")
# the mark on a result reported from a re-spiked dilution the method
# qualifies; SENAITE answers it with the QAO's qualifier (QC Qualifiers)
RESPIKE_FLAG = "RESPIKE"


def settings_of(profile_data) -> dict:
    return dict((profile_data or {}).get("dilution") or {})


def surrogate_added(entry) -> bool:
    entry = entry or {}
    return entry.get("route") == "respike" or entry.get("sur_handling") in ADDED


def dilution_rule(rule, settings):
    """The method's surrogate window for a diluted injection: its low end the
    lowest EIS recovery in a diluted extract when the method sets one."""
    floor = (settings or {}).get("eis_floor_pct")
    if rule is None or floor in (None, ""):
        return rule
    return dataclasses.replace(rule, recovery_min=float(floor))


def file_under(injection: str, dilutions) -> str:
    """The injection a check result is filed under: a dilution has no review
    checks of its own, so its result goes to the sample it was diluted from
    (the flag still names the dilution)."""
    entry = (dilutions or {}).get(injection) or {}
    return entry.get("parent") or injection


def qualifies_respike(entry, settings) -> bool:
    """A result reported from a re-spiked dilution is qualified when the
    method says so (the qualifier's code and wording are the QAO's, in QC
    Qualifiers)."""
    return (entry or {}).get("route") == "respike" and bool((settings or {}).get("qualify_respike"))


def fold_applies(entry, settings, role) -> bool:
    """Whether a dilution's reading is multiplied by its fold. The method's
    choice: always (the default), or only when the standard that quantifies
    the analyte was added to the dilution -- with none added the native and
    its standard were diluted together and the reading is the undiluted one.
    `role`: the quantifying standard's role in the method ("injection_is",
    else a surrogate / extracted standard)."""
    if (settings or {}).get("fold_rule") != "added":
        return True
    entry = entry or {}
    if role == "injection_is":
        return entry.get("is_handling") in ADDED
    return surrogate_added(entry)
