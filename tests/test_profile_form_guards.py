"""A pane that writes must be guarded by a marker field.

The method-profile form is one big POST covering many panes. Its save handler
assigns most values UNCONDITIONALLY -- `_float("cal_point_pct_dev_max")`
returns None for an absent field and that None is stored. So a POST that omits
a pane's inputs does not leave that pane alone; it NULLS it.

The codebase already knew this. `matrix_settings_present` carries a comment
saying a POST from another pane "cannot wipe the matrix list", and the recovery
tiers are guarded because blanking them "would stop every run". The instrument
verification block was simply missed, and on 2026-08-06 a partial POST sent
while verifying something else wiped, off the LIVE FDA profile:

    calibration.point_pct_dev_max      20.0 -> None
    confirmation.ion_ratio_tol_pct     30.0 -> None
    confirmation.rrt_tol_pct            1.0 -> None
    confirmation.sn_quan_min            3.0 -> None
    confirmation.sn_confirm_min         3.0 -> None
    confirmation.require_confirm_ion_check True -> False
    is_response.vs_ical_avg_min/max  50/150 -> None

Every one of those decides whether a result passes QC. The full form always
submits every pane, so normal use never hit it -- which is exactly why it
survived. These tests assert the guard by STRUCTURE rather than by replaying a
POST, so a new pane added later is covered without anyone remembering to.
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLER = os.path.join(ROOT, "src", "senaite", "pfas", "browser",
                       "method_profiles.py")
TEMPLATE = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "templates",
                        "method_profile_edit.pt")

#: Every marker the save handler gates a pane on. Each must also be emitted by
#: the template, or the pane silently stops saving.
MARKERS = (
    "qc_rules_present",
    "matrix_present",
    "matrix_settings_present",
    "instrument_verification_present",
    "eis_matrix_present",
    "surrogate_chain_present",
    "salt_present",
    "qc_toggles_present",
)


def _handler_source():
    with open(HANDLER) as fh:
        return fh.read()


def _template_source():
    with open(TEMPLATE) as fh:
        return fh.read()


def test_every_marker_the_handler_reads_is_emitted_by_the_form():
    """A guard the form never sets turns the pane read-only, silently."""
    handler, template = _handler_source(), _template_source()
    for marker in MARKERS:
        # quoted: "matrix_present" is a substring of "eis_matrix_present"
        if '"{0}"'.format(marker) not in handler:
            continue
        assert 'name="{0}"'.format(marker) in template, (
            "%s guards a pane in the save handler but the form never emits it "
            "-- that pane can no longer be saved" % marker)


def test_every_marker_the_form_emits_is_honoured_by_the_handler():
    """The mirror: a marker nothing reads is a guard that does not guard."""
    handler, template = _handler_source(), _template_source()
    emitted = set(re.findall(r'name="(\w+_present)"', template))
    for marker in sorted(emitted):
        assert marker in handler, (
            "the form emits %s but the save handler never checks it" % marker)


def test_the_instrument_criteria_are_saved_only_by_their_own_section():
    """The specific regression. These seven were nulled by a partial POST.

    Since R2 (2026-09-30) the guard is structural rather than a marker: the
    big-form handler writes NONE of them, and the Calibration & CCV section
    (method_profile_sections, config_forms) is the only writer -- and it
    parses only when its own form is submitted. Any assignment of one of these
    keys back in the handler would re-open the partial-POST hole.
    """
    import sys
    sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))
    import method_profile_sections as mps
    victims = ("point_pct_dev_max", "ion_ratio_tol_pct", "rrt_tol_pct",
               "sn_quan_min", "sn_confirm_min", "vs_ical_avg_min",
               "require_confirm_ion_check")
    declared = set(f.path[-1] for f in mps.CALIBRATION_CCV.fields())
    assert set(victims) <= declared, sorted(set(victims) - declared)

    written = set()

    class Visitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            for t in node.targets:
                if isinstance(t, ast.Subscript):
                    key = t.slice
                    if key.__class__.__name__ == "Index":
                        key = key.value
                    name = key.value if hasattr(key, "value") else getattr(key, "s", None)
                    if name in victims:
                        written.add(name)
            self.generic_visit(node)

    Visitor().visit(ast.parse(_handler_source(), HANDLER))
    assert not written, (
        "the big-form handler writes %s again -- a POST from any other tab "
        "would null it; it belongs to the Calibration & CCV section only"
        % sorted(written))


def test_absent_means_unchanged_not_zero():
    """`_float` returning None is the mechanism behind the whole defect. If it
    ever starts defaulting to 0.0 instead, an omitted field would set a limit of
    zero rather than clearing it -- worse, and silent."""
    source = _handler_source()
    match = re.search(r"def _float\(.*?\n(?:.*?\n)*?\s*return .*?\n", source)
    assert match, "could not find _float in the save handler"
    body = match.group(0)
    assert "0.0" not in body.replace("0.0)", ""), (
        "_float appears to default to a number; an absent field must not "
        "become a real limit")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
