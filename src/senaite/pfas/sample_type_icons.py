# -*- coding: utf-8 -*-
"""One icon per group of sample types, the same wherever a type is named.

A type belongs to one of five groups, each drawn once: Samples, Spiked,
Blanks, Checks and Calibration, and Not judged for an injection a reviewer
took out of the run. The exact type, and a level where it matters, is the
word beside the icon, never a second drawing. The icon is a line drawing on
the sidebar's 24 grid with one filled accent; it takes its group's colour
token (--type-<group>) and draws in currentColor only, so a forced-colours
screen draws it in CanvasText. No group is drawn as a circle: circles are the
limit box states.

    group_of(code)              -> "samples" | ... | None
    label(code, sub=None)       -> "Spiked: LFSM"
    svg(code, sub=None, na=False, hidden=False)  one icon
    cell(code, words=None)      an icon and its words, for a table cell
    applies(rule_key, profile, off=False)  {group: [codes]} a rule judges
    row(rule_key, profile, off=False)      the Applies to row of a rule
    spec()                      what pfas-components.js draws from (the
                                same drawings, one source)

The certificate never shows a type icon: it is a formal document.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

from senaite.pfas.html_text import escape

GROUPS = ("samples", "spiked", "blanks", "checks", "calibration", "not_judged")
# the Applies to row: every group a rule can judge, in this order
ROW = ("samples", "spiked", "blanks", "checks", "calibration")
WORDS = {"samples": "Samples", "spiked": "Spiked", "blanks": "Blanks", "checks": "Checks",
         "calibration": "Calibration", "not_judged": "Not judged"}

# The sample duplicate is no spike: the engine judges it by its RPD against
# its parent, and extraction_batch.SPIKED leaves it out, so it is a Sample.
_CODES = {
    "samples": ("SAMPLE", "FD", "DILUTION", "DUP"),
    "spiked": ("LFB", "LCS", "LFSM", "LFSMD"),
    "blanks": ("MB", "LRB", "MXB", "FRB", "FB", "TB", "CCB", "SOLVENT_BLANK", "SOLVENT", "BLANK"),
    # QCS and CCC are EPA 537.1's names for the ICV and the CCV
    "checks": ("ICV", "QCS", "CCV", "CCC", "CCV_LOW"),
    "calibration": ("CAL", "CALIBRATION", "CALIBRATOR"),
    "not_judged": ("NOTJUDGED", "NOT_JUDGED"),
}
CODE_GROUP = dict((c, g) for g, codes in _CODES.items() for c in codes)

# The drawings, 24 x 24, a 1.5 line (the class sets it) and one accent
# (class pfas-type-a, filled). Inner markup only: svg() wraps it.
DRAWINGS = {
    # a rounded square holding a solid core: the sample itself
    "samples": ('<rect x="3.75" y="3.75" width="16.5" height="16.5" rx="3.5"/>'
                '<rect class="pfas-type-a" x="8.5" y="8.5" width="7" height="7" rx="1.5"/>'),
    # a hexagon holding a plus: something added in a known amount
    "spiked": ('<path d="M12 2.75 20.25 7.5v9L12 21.25 3.75 16.5v-9Z"/>'
               '<path class="pfas-type-a" d="M10.9 7.75h2.2v3.15h3.15v2.2H13.1v3.15h-2.2V13.1H7.75v-2.2h3.15Z"/>'),
    # an empty vessel with only its floor drawn in: nothing should be found
    "blanks": ('<path d="M3.75 4.75h16.5l-2.6 14.5H6.35Z"/>'
               '<path class="pfas-type-a" d="M6.6 16.6h10.8l-.45 2.65H7.05Z"/>'),
    # brackets round a solid bar: a standard that brackets the run
    "checks": ('<path d="M8 3.75H4.25v16.5H8"/><path d="M16 3.75h3.75v16.5H16"/>'
               '<rect class="pfas-type-a" x="9.5" y="8" width="5" height="8" rx="1"/>'),
    # axes holding three rising bars: the calibration levels
    "calibration": ('<path d="M3.75 3.75v16.5h16.5"/>'
                    '<rect class="pfas-type-a" x="7" y="13.5" width="3" height="4.5" rx=".6"/>'
                    '<rect class="pfas-type-a" x="11.5" y="10" width="3" height="8" rx=".6"/>'
                    '<rect class="pfas-type-a" x="16" y="6" width="3" height="12" rx=".6"/>'),
    # a short bar: no role in the run
    "not_judged": '<rect class="pfas-type-a" x="5" y="10.75" width="14" height="2.5" rx="1.25"/>',
}

NA = "does not apply"


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return "%s" % (value,)


def _esc(text):
    # the project's one HTML escape
    return escape(_text(text))


def _key(code):
    """A code as the map reads it: upper case, a level suffix dropped
    ("CAL-3", "CCV low"), spaces as underscores."""
    text = _text(code).strip().upper()
    if not text:
        return ""
    if text in CODE_GROUP:
        return text
    head = text.replace("-", " ").split()[0]
    return head if head in CODE_GROUP else text.replace(" ", "_")


def group_of(code):
    """The group of a type code, or of a group's own name; None for a code no
    group holds (a compound role, an unknown word)."""
    text = _text(code).strip()
    if text in WORDS:
        return text
    return CODE_GROUP.get(_key(text))


def label(code, sub=None):
    """The accessible name: the group, then the type ("Spiked: LFSM"); the
    group alone when `code` is a group."""
    g = group_of(code)
    if g is None:
        return _text(code)
    word = WORDS[g]
    if g == "not_judged":
        return word
    sub = _text(sub) if sub is not None else ("" if _text(code).strip() in WORDS else _text(code).strip())
    return "%s: %s" % (word, sub) if sub else word


def svg(code, sub=None, na=False, hidden=False):
    """One icon. `na`: the type does not apply (the Applies to row's pale
    icon). `hidden`: a word beside it says the same, so a screen reader
    skips it; the title still shows on hover."""
    g = group_of(code)
    if g is None:
        return ""
    name = label(code, sub)
    if na:
        name = "%s: %s" % (WORDS[g], NA)
    attrs = 'aria-hidden="true"' if hidden else 'role="img" aria-label="%s"' % _esc(name)
    return ('<svg class="pfas-type is-%s%s" viewBox="0 0 24 24" focusable="false" %s><title>%s</title>%s</svg>'
            % (g.replace("_", "-"), " is-na" if na else "", attrs, _esc(name), DRAWINGS[g]))


def cell(code, words=None):
    """An icon and the words beside it ("LFB Mid"), for a table cell or a
    choice; the words default to the code. A code no group holds is its
    words alone."""
    words = _text(code) if words is None else _text(words)
    icon = svg(code, sub=words, hidden=True)
    if not icon:
        return _esc(words)
    return '<span class="pfas-type-cell">%s<span>%s</span></span>' % (icon, _esc(words))


def cells(text, sep=", "):
    """A list in words ("MB 1, LFB 1"), each item an icon and its words
    where its first word names a type; an item no group holds stays words."""
    return _esc(sep).join(cell(item) for item in _text(text).split(sep))


def change(entry):
    """A change of type in words ("Undone: CCV to Sample"), each type with
    its icon: the entry's change, from_code, from_label, to_code and
    to_label. The words stay as they are; a change that does not end in
    "<from_label> to <to_label>" is its words alone."""
    e = entry or {}
    words = _text(e.get("change"))
    tail = "%s to %s" % (_text(e.get("from_label")), _text(e.get("to_label")))
    if not (e.get("from_code") or e.get("to_code")) or not words.endswith(tail):
        return _esc(words)
    return "%s%s to %s" % (_esc(words[:len(words) - len(tail)]), cell(e.get("from_code"), e.get("from_label")),
                           cell(e.get("to_code"), e.get("to_label")))


def result_code(field_qc=None, dilution=False):
    """The type a list of results names beside a sample: a dilution retest,
    else the sample's field QC ("FRB", "TB", "FD"); "" for a plain field
    sample, which carries no icon."""
    code = "Dilution" if dilution else _text(field_qc).strip()
    if not code or group_of(code) is None or _key(code) == "SAMPLE":
        return ""
    return code


# -- the Applies to row ------------------------------------------------------
#
# What each rule judges, read from the engine (pfas_pipeline: run_queue's
# auto_evaluate, qc_engine's checks, pipeline.build_summary). The worker is a
# separate process, so the add-on cannot import it; tests/test_r17_icons.py
# reads the engine's own lists and fails when one drifts from these.
EVERY = ("Sample", "FD", "Dilution", "Dup", "LFB", "LCS", "LFSM", "LFSMD", "MB", "LRB", "MxB", "FRB", "TB",
         "CCB", "ICV", "CCV", "CAL")
# the injections on the sample basis: every one but the run's standards and
# the solvent blank (pipeline._NO_SAMPLE_BASIS_ROLES)
SAMPLE_BASIS = ("Sample", "FD", "Dilution", "Dup", "LFB", "LCS", "LFSM", "LFSMD", "MB", "LRB", "MxB", "FRB", "TB")
# the roles a result is reported for (pipeline.build_summary REPORTED_ROLES):
# the MDL check and the single-transition confirmation judge these only
REPORTED = ("Sample", "MB", "LFSM", "LFSMD")
# the extraction batch's QC and the field QC (qc_engine.EXTRACTED_QC_ROLES)
EXTRACTED_QC = ("MB", "LRB", "MxB", "LFB", "LCS", "LFSM", "LFSMD", "Dup", "FRB", "FD")
# the blanks judged against Blank limits (qc_engine.BLANK_ROLES, with the
# field and trip blanks the run queue adds)
BLANKS = ("MB", "LRB", "MxB", "CCB", "FRB", "TB")
# every injection but a dilution: RT, ion ratio and S/N filter no role
NOT_DILUTED = tuple(c for c in EVERY if c != "Dilution")

RULE_TYPES = {
    "cal_r2": ("CAL",),
    "over_range": SAMPLE_BASIS,
    "ccv_recovery": ("CCV",),            # and the ICV where it is judged by the CCV's window
    "icv": ("ICV",),
    # a TB and a dilution are read by name in the count, so they count
    # always; extracted and field QC only where the method counts them
    "ccv_frequency": ("Sample", "Dilution", "TB"),
    "rrt_deviation": NOT_DILUTED,
    "ion_ratio": NOT_DILUTED,
    "sn_min": NOT_DILUTED,
    "single_transition_confirm": REPORTED,
    "mdl_check": REPORTED,
    "is_response": EVERY,
    "is_vs_ccv": EVERY,
    # extracted injections only; a CCV where the method judges surrogates
    # in its CCVs; a dilution only by the method's dilution choice
    "surrogate_recovery": tuple(c for c in SAMPLE_BASIS if c != "Dilution"),
    "low_level_recovery": ("LFB", "LCS", "LFSM", "LFSMD"),
}
# a QC type's or blank's own row: that type; an LFSM row judges the LFSMD's
# recovery too
ROW_TYPES = {"LFSM": ("LFSM", "LFSMD")}
# what a method always runs; the rest it runs where it switches the type on
ALWAYS = ("Sample", "Dilution", "CAL", "ICV", "CCV")


def _iv(profile):
    p = profile or {}
    return p.get("instrument_verification") or p


def runs(profile):
    """The types a method runs: its switched-on QC types (qc_acceptance),
    the CCB where its run template holds one, and what every run holds."""
    out = set(ALWAYS)
    for code, conf in ((profile or {}).get("qc_acceptance") or {}).items():
        if isinstance(conf, dict) and conf.get("enabled"):
            out.add(_text(code))
    tpl = (profile or {}).get("run_template") or {}
    seq = [_text(c).upper() for c in (tpl.get("sequence") or (tpl.get("opening") or []) + (tpl.get("closing") or []))]
    if "CCB" in seq or _text(tpl.get("bracket_qc")).upper() == "CCB":
        out.add("CCB")
    return out


def judged(rule_key, profile):
    """The types a rule judges on this method, as the engine does."""
    key = _text(rule_key)
    for prefix in ("qc_type.", "blank."):
        if key.startswith(prefix):
            code = key[len(prefix):]
            types = set(ROW_TYPES.get(code, (code,)))
            break
    else:
        types = set(RULE_TYPES.get(key.split(".")[0], ()))
        ccv = _iv(profile).get("ccv") or {}
        if key == "ccv_recovery" and (_iv(profile).get("icv") or {}).get("criteria") == "ccv":
            types.add("ICV")
        if key == "ccv_frequency" and ccv.get("counts_extracted_qc") != "no":
            types.update(EXTRACTED_QC)
        if key == "surrogate_recovery" and ccv.get("surrogate_recovery") in (True, "yes"):
            types.add("CCV")
    return types & runs(profile)


def applies(rule_key, profile, off=False):
    """{group: [codes]} the rule judges on this method; nothing while the
    rule is Off."""
    if off:
        return {}
    out = {}
    for code in sorted(judged(rule_key, profile)):
        g = group_of(code)
        if g:
            out.setdefault(g, []).append(code)
    return out


def row(rule_key, profile, off=False):
    """The Applies to row: each group lit where the rule judges a type of it
    on this method, pale where it judges none. Its hover names the types."""
    lit = applies(rule_key, profile, off)
    items = []
    for g in ROW:
        if g in lit:
            items.append(svg(g, sub=", ".join(lit[g])))
        else:
            items.append(svg(g, na=True))
    return ('<span class="pfas-type-row" role="group" aria-label="Applies to">'
            '<span class="pfas-type-row-l" aria-hidden="true">Applies to</span>%s</span>' % "".join(items))


def spec():
    """The drawings and the code map as JSON, for pfas-components.js."""
    # "</" never closes the script element it is written into
    return json.dumps({"drawings": DRAWINGS, "words": WORDS, "codes": CODE_GROUP, "na": NA},
                      sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
