# -*- coding: utf-8 -*-
"""A QC rule's flag: the code it prints when it fails, where that code
attaches, and the internal note reviewers see beside the flag.

    {"code": a QC Qualifiers entry's key ("ion_ratio") or "" (No code),
     "attach": "result" | "analyte" | "injection" | "batch",
     "output": "" (the certificate and the EDD) | "coa" | "edd",
     "note": text for reviewers, never printed}

The code is the library ENTRY, never its letter: the letter and the wording
are the QAO's (QC Qualifiers), read when the code prints, and two entries may
share a letter.

Where a flag is stored:
  a rule (a rule library key, a QC type's or blank's row, the Low-level
  recoveries row)   profile["engine"]["rule_flags"][rule key]
  its further flags profile["engine"]["rule_flags_more"][rule key] = [flag]
  a recovery tier   the tier itself: qc_acceptance[qc]["tiers"][i]["flag"]
Only what is set is stored.

A rule also raises the code of its kind of exceedance (flag_kinds), at the
place and output of its first flag: every rule of one kind attaches the
same code. Only an Enforced failure prints; an Evaluate failure is an
advisory for Data Review alone.

The notes the Engine once held for every rule (engine.rule_notes) are moved
onto the rules and tiers that used them (migrate), word for word, a note
several rules shared copied to each. Pure; Python 2.7 and 3: the worker loads
it through pfas_pipeline.addon.
"""
from __future__ import absolute_import, unicode_literals

import copy

FLAGS_KEY = "rule_flags"
TIER_FLAG_KEY = "flag"
LEGACY_KEY = "rule_notes"
MORE_KEY = "rule_flags_more"
FIELDS = ("code", "attach", "output", "note")

# where a code is issued: both (stored as nothing), the certificate alone,
# the EDD alone
BOTH, COA, EDD = "", "coa", "edd"
OUTPUTS = ((BOTH, "Certificate and EDD"), (COA, "Certificate only"), (EDD, "EDD only"))
OUTPUT_WORDS = dict(OUTPUTS)

RESULT, ANALYTE, INJECTION, BATCH = "result", "analyte", "injection", "batch"
ATTACH = ((RESULT, "Result"), (ANALYTE, "Analyte row"), (INJECTION, "Injection"),
          (BATCH, "Batch or report"))
ATTACH_WORDS = dict(ATTACH)
ATTACH_HELP = {
    RESULT: "The single result: the code prints beside the one value that failed.",
    ANALYTE: "The analyte row: the code prints on that analyte for every sample on the report.",
    INJECTION: "The injection: the code prints on every result from that injection.",
    BATCH: "The batch or report: the code covers everything on it.",
}
DEFAULT_ATTACH = RESULT

# the Low-level recoveries row (qc.rules.LOW_LEVEL_ROW)
LOW_LEVEL_RULE = "low_level_recovery"
LOW_LEVEL_KEY = "low_level_x_rl"

# Where each Engine note moves: the rules that carried it.
NOTE_MOVES = (
    ("eis", ("surrogate_recovery",)),
    ("is_rule", ("is_response", "is_vs_ccv")),
    ("confirmation_rule", ("ion_ratio", "rrt_deviation", "sn_min")),
    ("tier_low_level", (LOW_LEVEL_RULE,)),
)
# The grouped tiers' notes, by the analyte group of the tier the engine
# chooses on that branch (qc_tiers.base_tier).
BRANCH_NOTES = {"key": "tier_key_tight", "no_std": "tier_no_std",
                "all": "tier_default", "linked": "tier_default"}
GENERIC_TIER_NOTE = "tier"


def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        v = v.decode("utf-8")
    return ("%s" % v).strip()


def clean(flag):
    """A flag as every reader takes it: the three fields as text, an
    unknown place read as the single result."""
    flag = flag if isinstance(flag, dict) else {}
    attach = _text(flag.get("attach"))
    output = _text(flag.get("output"))
    return {"code": _text(flag.get("code")),
            "attach": attach if attach in ATTACH_WORDS else DEFAULT_ATTACH,
            "output": output if output in OUTPUT_WORDS else BOTH,
            "note": _text(flag.get("note"))}


def is_empty(flag):
    """Nothing set: no code, no note, the default place and output. A
    place or an output alone is a setting: the rule's kind code prints
    there."""
    f = clean(flag)
    return not f["code"] and not f["note"] and f["attach"] == DEFAULT_ATTACH and f["output"] == BOTH


def _stored(flag):
    """What is stored for a flag: only the fields set; the default place is
    not stored."""
    f = clean(flag)
    out = dict((k, f[k]) for k in ("code", "note", "output") if f[k])
    if f["attach"] != DEFAULT_ATTACH:
        out["attach"] = f["attach"]
    return out


def _engine(profile):
    eng = (profile or {}).get("engine")
    return eng if isinstance(eng, dict) else {}


def is_legacy(profile):
    """True while the profile still holds the Engine's notes (not migrated)."""
    return isinstance(_engine(profile).get(LEGACY_KEY), dict)


def _view(profile):
    """The profile as its flags read: migrated on a copy when it is not yet."""
    if not is_legacy(profile):
        return profile or {}
    view = copy.deepcopy(profile)
    migrate(view)
    return view


def flags(profile):
    """{rule key: flag} of the rules that hold one (tiers apart)."""
    stored = _engine(_view(profile)).get(FLAGS_KEY) or {}
    return dict((_text(k), clean(v)) for k, v in stored.items() if isinstance(v, dict))


def flag_of(profile, rule_key):
    return flags(profile).get(_text(rule_key)) or clean(None)


def set_flag(profile, rule_key, flag):
    """Store one rule's flag (removed when nothing is set). The profile,
    changed in place."""
    eng = profile.get("engine")
    eng = eng if isinstance(eng, dict) else {}
    stored = dict(eng.get(FLAGS_KEY) or {})
    value = _stored(flag)
    if value and not is_empty(value):
        stored[rule_key] = value
    else:
        stored.pop(rule_key, None)
    if stored or FLAGS_KEY in eng:
        eng[FLAGS_KEY] = stored
    if eng or "engine" in profile:
        profile["engine"] = eng
    return profile


def more_flags(profile, rule_key):
    """The rule's further flags ("multiple flags if needed"), each read as
    clean reads one; [] when it has none."""
    eng = _engine(profile)
    stored = (eng.get(MORE_KEY) or {}).get(_text(rule_key)) if isinstance(eng.get(MORE_KEY), dict) else None
    return [clean(f) for f in stored or [] if isinstance(f, dict) and not is_empty(f)]


def set_more_flags(profile, rule_key, flags):
    """Store the rule's further flags (removed when none is set). The
    profile, changed in place."""
    eng = profile.setdefault("engine", {})
    stored = dict(eng.get(MORE_KEY) or {})
    kept = [_stored(f) for f in flags or [] if not is_empty(f)]
    if kept:
        stored[rule_key] = kept
    else:
        stored.pop(rule_key, None)
    if stored or MORE_KEY in eng:
        eng[MORE_KEY] = stored
    return profile


def rule_flag_list(profile, rule_key):
    """Every flag the rule carries: its first (rule_flags) then its further
    ones. A profile stored before further flags existed reads its one flag:
    nothing to migrate, nothing written."""
    first = flag_of(profile, rule_key)
    return [first] + more_flags(profile, rule_key)


def tier_name(tier, index):
    """A tier's name as the tier collection reads it."""
    return _text((tier or {}).get("name")) or "tier %d" % (index + 1)


def tiers_of(profile, qc_type):
    entry = ((profile or {}).get("qc_acceptance") or {}).get(qc_type)
    tiers = entry.get("tiers") if isinstance(entry, dict) else None
    return [t for t in tiers or [] if isinstance(t, dict)]


def find_tier(profile, qc_type, name):
    """The ordinary tier of `qc_type` named `name`, or None."""
    for i, t in enumerate(tiers_of(profile, qc_type)):
        if not t.get(LOW_LEVEL_KEY) and tier_name(t, i) == _text(name):
            return t
    return None


def tier_flag(tier):
    return clean((tier or {}).get(TIER_FLAG_KEY))


def tier_flag_in(profile, qc_type, name):
    """A tier's flag as the profile reads (migrated when it is not yet)."""
    return tier_flag(find_tier(_view(profile), qc_type, name))


def set_tier_flag(tier, flag):
    value = _stored(flag)
    if value and not is_empty(value):
        tier[TIER_FLAG_KEY] = value
    else:
        tier.pop(TIER_FLAG_KEY, None)
    return tier


# ── migration: the Engine's notes onto their rules ─────────────────────────

def migrate(profile):
    """Move engine.rule_notes onto the rules and tiers that used them, word
    for word, and remove it. A note a flag already holds is kept. Returns
    True when the profile changed. Idempotent."""
    eng = _engine(profile)
    notes = eng.get(LEGACY_KEY)
    if not isinstance(notes, dict):
        return False
    notes = dict((_text(k), _text(v)) for k, v in notes.items() if _text(v))
    stored = dict(eng.get(FLAGS_KEY) or {})

    def put(key, text):
        f = dict(stored.get(key) or {})
        if not _text(f.get("note")):
            f["note"] = text
        stored[key] = f
    for legacy, targets in NOTE_MOVES:
        if notes.get(legacy):
            for key in targets:
                put(key, notes[legacy])
    generic = notes.get(GENERIC_TIER_NOTE)
    for qc_type, entry in ((profile.get("qc_acceptance") or {}).items()):
        if not isinstance(entry, dict):
            continue
        if generic and entry.get("tiers"):
            # the note a QC type's tiers carry when they say nothing
            # themselves: on the QC type's own row (type_note)
            key = _row_key(qc_type)
            if key:
                put(key, generic)
        for t in entry.get("tiers") or []:
            if not isinstance(t, dict) or t.get(LOW_LEVEL_KEY):
                continue
            branch = BRANCH_NOTES.get(_text(t.get("analyte_group")) or "all")
            text = notes.get(branch) if branch else ""
            if text and not tier_flag(t)["note"]:
                f = dict(t.get(TIER_FLAG_KEY) or {})
                f["note"] = text
                t[TIER_FLAG_KEY] = f
    eng.pop(LEGACY_KEY, None)
    if stored:
        eng[FLAGS_KEY] = stored
    profile["engine"] = eng
    return True


def _row_key(qc_type):
    """A QC type's own row key; a type the lab's list does not name (a
    field blank judged by its tiers) is keyed as a QC type all the same, so
    the note its tiers fall back to is kept."""
    from senaite.pfas.qc import rules
    return rules.qc_row_key(qc_type) or (rules.QC_TYPE_KEY(qc_type) if qc_type else None)


def type_note(profile, qc_type):
    """The note of a QC type's own row: what its tiers carry when neither
    their flag nor a description says anything (the Engine's general tier
    note, moved there)."""
    key = _row_key(qc_type)
    return flag_of(profile, key)["note"] if key else ""


def legacy_notes(profile):
    """{note key: text} as the worker's rules read them (method_engine
    rule_notes): the Engine's own notes while a profile is not migrated,
    else the notes of the rules that carry them on."""
    eng = _engine(profile)
    if is_legacy(profile):
        return dict(eng.get(LEGACY_KEY) or {})
    stored = eng.get(FLAGS_KEY) or {}
    out = {}
    for legacy, targets in NOTE_MOVES:
        note = clean(stored.get(targets[0]))["note"]
        if note:
            out[legacy] = note
    return out


# ── which rule a QC result belongs to ──────────────────────────────────────

# the stored QC types of the instrument checks, by the rule that judges them
# ("Above the calibration range" is above_range.QC_TYPE)
INSTRUMENT_RULES = {
    "Calibration": "cal_r2", "CCV": "ccv_recovery", "ICV": "ccv_recovery",
    "IS": "is_response", "IS Response": "is_response",
    "RT": "rrt_deviation", "Ion ratio": "ion_ratio", "S/N": "sn_min",
    "Surrogate": "surrogate_recovery",
    "Above the calibration range": "over_range",
}
# a CCV row that judges the bracket, not the recovery (the worker's issue)
CCV_FREQUENCY_MARKS = ("(CCV) run", "no CCV after")
MDL_MARK = "(MDL)"


# the QC types a labelled compound's response is filed under: a surrogate's
# is its recovery (Surrogate Recovery), the injection standard's its response
IS_TYPES = ("IS", "IS Response")


def rule_for_qc_row(row, role_of=None):
    """The rule key a failing QC row is judged by: an instrument check's
    rule, else its QC type's or blank's row; None for a row no rule card
    holds. `role_of(compound)` -> "surrogate" | "injection_is" | "": an
    IS row of a surrogate is Surrogate Recovery's."""
    qc_type = _text((row or {}).get("qc_type"))
    issue = _text((row or {}).get("flag"))
    if qc_type in IS_TYPES and role_of is not None and \
            role_of(_text((row or {}).get("analyte"))) == "surrogate":
        return "surrogate_recovery"
    if qc_type == "CCV" and any(m in issue for m in CCV_FREQUENCY_MARKS):
        return "ccv_frequency"
    if MDL_MARK in issue:
        return "mdl_check"
    if qc_type in INSTRUMENT_RULES:
        return INSTRUMENT_RULES[qc_type]
    from senaite.pfas.qc import rules
    return rules.qc_row_key(qc_type)


def resolve(profile, rule_key, tier=None):
    """The flag that applies: the tier's when it carries a code, else the
    rule's."""
    if tier is not None and tier_flag(tier)["code"]:
        return tier_flag(tier)
    return flag_of(profile, rule_key)


# ── the QC Qualifiers library as the Code list offers it ──────────────────

def code_entries(library):
    """[{"key", "code", "label", "statement"}]: the library entries that
    carry a code, code first then the failure it was written for."""
    out = []
    for key, entry in (library or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        code = _text(entry.get("code"))
        if code:
            out.append({"key": _text(key), "code": code, "label": _text(entry.get("label")) or _text(key),
                        "statement": _text(entry.get("statement"))})
    return sorted(out, key=lambda e: (e["code"].lower(), e["label"].lower()))


def printed(library, flag):
    """(code letter, wording) a flag prints, ("", "") for none: its entry's
    code and wording as the library holds them now."""
    key = clean(flag)["code"]
    entry = (library or {}).get(key) if key else None
    if not isinstance(entry, dict):
        return "", ""
    return _text(entry.get("code")), _text(entry.get("statement"))


# ── where a failing rule's code lands: the worksheet's qualifier plan ─────
# A rule's code is an entry of the plan Data Review builds for the stamp,
# Final Data, the certificate and the EDD, scoped by its place:
#   result     the affected analytes, on the sample the failure belongs to
#   analyte    the affected analytes, on every sample of the worksheet
#   injection  every result of the sample the failing injection belongs to
#              (the whole run when it belongs to none)
#   batch      every sample: printed once for the report, never per row
# A rule with no code changes nothing: the library maps the failure as before.

def failing(row):
    """A QC row that failed: judged (not voided, not unevaluated) and not
    passed, Evaluate's included (enforced tells them apart)."""
    row = row or {}
    if row.get("result_status") in ("voided", "unevaluated"):
        return False
    return not row.get("passed", 1)


def enforced(row):
    """A failure that prints: its rule was Enforced. An Evaluate rule's
    failure (the worker's advisory mark) is advice for the reviewer alone,
    and an Off rule is never judged."""
    return not (row or {}).get("advisory")


def row_flags(profile, row, library, tier_of=None, role_of=None):
    """(rule key, kind, [flag]) a failing row raises: its kind's flag
    (code = the kind's QC Qualifiers entry) at the place and output of the
    rule's first flag (its tier's when the tier carries a code), then the
    rule's own flags that carry a code: the tier's (else the rule's first),
    then its further flags. (None, "", []) for a row no rule card holds."""
    from senaite.pfas import flag_kinds
    rule = rule_for_qc_row(row, role_of)
    if not rule:
        return None, "", []
    tier = tier_of(row) if tier_of is not None else None
    first = resolve(profile, rule, tier)
    kind = flag_kinds.kind_of(profile, rule)
    out = []
    if kind:
        out.append(dict(first, code=flag_kinds.library_key(kind), note=""))
    if first["code"]:
        out.append(first)
    out += [f for f in more_flags(profile, rule) if f["code"]]
    return rule, kind, out


def printing_flags(profile, row, library, tier_of=None, role_of=None):
    """(rule key, [flag]) of the row's flags that print a code now (the
    library gives their entry a code)."""
    rule, _kind, flags = row_flags(profile, row, library, tier_of, role_of)
    return rule, [f for f in flags if printed(library, f)[0]]


def advisory_entries(profile, row, library, tier_of=None, role_of=None):
    """What an Evaluate failure would have raised, for Data Review alone:
    one entry per flag (the kind's even with no code), each marked not
    printed. [] for a rule with no kind and no code of its own."""
    from senaite.pfas import flag_kinds
    rule, kind, flags = row_flags(profile, row, library, tier_of, role_of)
    out = []
    for f in flags:
        letter, wording = printed(library, f)
        is_kind = flag_kinds.is_kind_entry(f["code"])
        out.append({"qc_type": _text(row.get("qc_type")), "analyte": _text(row.get("analyte")),
                    "applies_to": _text(row.get("applies_to")), "reason": _text(row.get("flag")),
                    "rule": rule, "kind": flag_kinds.name(kind) if is_kind else "",
                    "code": letter, "statement": wording, "printed": False})
    return out


def flag_for_row(profile, row, tier_of=None):
    """(rule key, flag) of a QC row: its tier's flag when the row is judged
    by a tier whose flag carries a code (tier_of(row) -> the tier or None),
    else its rule's; (None, empty flag) for a row no rule card holds."""
    rule = rule_for_qc_row(row)
    if not rule:
        return None, clean(None)
    tier = tier_of(row) if tier_of is not None else None
    return rule, resolve(profile, rule, tier)


def flag_entries(row, rule, flag, library, analytes, all_analytes="*"):
    """The plan's entries a failing row's flag adds: [] when the flag
    prints no code. `analytes`: the reported analytes the failure touches
    (a surrogate's natives)."""
    letter, wording = printed(library, flag)
    if not letter:
        return []
    place = clean(flag)["attach"]
    base = {"qc_type": _text(row.get("qc_type")), "reason": _text(row.get("flag")), "code": letter,
            "statement": wording, "place": place, "rule": rule, "output": clean(flag)["output"]}
    applies_to = _text(row.get("applies_to"))
    names = [a for a in analytes or [] if a] or [all_analytes]
    if place == RESULT:
        return [dict(base, analyte=a, applies_to=applies_to) for a in names]
    if place == ANALYTE:
        return [dict(base, analyte=a, applies_to="") for a in names]
    if place == INJECTION:
        return [dict(base, analyte=all_analytes, applies_to=applies_to)]
    return [dict(base, analyte=all_analytes, applies_to="")]


def replaced(profile, library, entry, failure_of, tier_of=None, role_of=None):
    """True for a library qualifier entry (no place) whose rule prints a
    code of its own or its kind's on the certificate: those codes, at their
    places, print instead (an EDD-only code leaves the certificate the
    library's). The entry names the compound its failure was recorded on
    (`source`, a surrogate's) and the library entry it came from
    (`failure`); else `failure_of`: {QC type: the library entry its failure
    maps to}."""
    if entry.get("place"):
        return False
    _rule, flags = printing_flags(profile, {"qc_type": entry.get("qc_type"), "flag": entry.get("reason"),
                                            "analyte": entry.get("source") or entry.get("analyte")},
                                  library, tier_of, role_of)
    if not [f for f in flags if clean(f)["output"] != EDD]:
        return False
    failure = _text(entry.get("failure")) or (failure_of or {}).get(_text(entry.get("qc_type")))
    mapped = _text(((library or {}).get(failure) or {}).get("code")) if failure else ""
    return bool(mapped) and _text(entry.get("code")) == mapped


def any_code(profile, library=None):
    """True when any rule or tier of the profile carries a code, or the
    library gives a kind a rule raises a code."""
    view = _view(profile)
    if any(f["code"] for f in flags(view).values()):
        return True
    eng = _engine(view)
    if any(more_flags(view, k) for k in (eng.get(MORE_KEY) or {})):
        return True
    from senaite.pfas import flag_kinds
    if any(flag_kinds.kind_flag(library, kind)[0] for kind in set(flag_kinds.kind_view(view).values())):
        return True
    for entry in ((view or {}).get("qc_acceptance") or {}).values():
        for t in (entry.get("tiers") or []) if isinstance(entry, dict) else []:
            if isinstance(t, dict) and tier_flag(t)["code"]:
                return True
    return False


def applies_everywhere(entry):
    """An entry on every sample of the worksheet: an analyte row's, or the
    batch's."""
    return (entry or {}).get("place") in (ANALYTE, BATCH)


def is_batch(entry):
    return (entry or {}).get("place") == BATCH


def on_certificate(entry):
    """An entry the certificate prints (and the release stamps): all but
    an EDD-only flag's."""
    return (entry or {}).get("output") != EDD


def on_edd(entry):
    """An entry the EDD issues: all but a certificate-only flag's."""
    return (entry or {}).get("output") != COA


# ── a note several rules share: once, on their group card ─────────────────

def shared_notes(profile, rule_keys):
    """[(note, [rule keys])]: the notes two or more of `rule_keys` (one
    group card's rules) carry word for word, in the rules' order. Read
    from the rules' own notes; nothing is stored or moved, so each rule
    keeps its note for the worker."""
    by_note, order = {}, []
    for key in rule_keys or []:
        note = flag_of(profile, key)["note"]
        if not note:
            continue
        if note not in by_note:
            by_note[note] = []
            order.append(note)
        by_note[note].append(key)
    return [(n, by_note[n]) for n in order if len(by_note[n]) > 1]
