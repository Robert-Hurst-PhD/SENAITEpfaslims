# -*- coding: utf-8 -*-
"""Declared configuration sections (R2, config_forms.py).

The rules every settings form must keep, tested once on the framework: an
unchanged save changes nothing (on the three LIVE method profiles), blank means
unset, required means refused, nothing is coerced, a choice cannot be widened by
the browser, and a section save touches only its own fields. Runs the real
modules without Zope, under Python 3 and 2.7.
"""
from __future__ import unicode_literals

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import config_forms as cf              # noqa: E402
import config_history as ch            # noqa: E402
import method_profile_sections as mps  # noqa: E402

SEC = mps.CALIBRATION_CCV


def _profiles():
    path = os.environ.get("PFAS_PROFILES_PATH") or os.path.join(
        os.path.dirname(HERE), "data", "qc", "method_profiles.json")
    with open(path) as fh:
        data = json.load(fh)
    data = data.get("profiles", data)
    return data if isinstance(data, dict) else dict((p["method_id"], p) for p in data)


def form_of(section, stored):
    """What the browser submits for an untouched page."""
    form = {}
    for g in cf.render(section, stored):
        for row in g["fields"]:
            if row["kind"] == cf.BOOL:
                if row["checked"]:
                    form[row["name"]] = "on"
            else:
                form[row["name"]] = row["value"]
    return form


def save(section, stored, form):
    updates, errors = cf.parse(section, form, stored)
    assert not errors, errors
    return cf.apply(section, stored, updates)


def test_an_unchanged_save_changes_nothing_on_every_live_profile():
    profiles = _profiles()
    assert set(profiles) >= set(["EPA_537_1", "EPA_1633A", "FDA_32PFAS"])
    for mid, stored in profiles.items():
        after = save(SEC, stored, form_of(SEC, stored))
        assert ch.diff(stored, after) == [], (mid, ch.diff(stored, after))
        assert cf.stamp(SEC, stored) == cf.stamp(SEC, after), mid


def test_unicode_submitted_as_utf8_bytes_round_trips():
    stored = _profiles()["EPA_537_1"]
    form = form_of(SEC, stored)
    form = dict((k, v.encode("utf-8") if not isinstance(v, bytes) else v) for k, v in form.items())
    assert "§" in stored["instrument_verification"]["is_response"]["notes"]
    assert ch.diff(stored, save(SEC, stored, form)) == []


def test_a_real_edit_is_exactly_that_edit():
    stored = _profiles()["EPA_537_1"]
    form = form_of(SEC, stored)
    form["f__ccv__recovery_max"] = "131"
    assert ch.diff(stored, save(SEC, stored, form)) == [
        (("instrument_verification", "ccv", "recovery_max"), 130.0, 131.0)]


def test_blank_optional_number_is_unset_not_zero():
    stored = _profiles()["EPA_537_1"]
    form = form_of(SEC, stored)
    form["f__ccv__low_level_max"] = "  "
    after = save(SEC, stored, form)
    assert after["instrument_verification"]["ccv"]["low_level_max"] is None


def test_blank_required_is_refused_and_named():
    stored = _profiles()["EPA_537_1"]
    form = form_of(SEC, stored)
    form["f__ccv__frequency"] = ""
    _u, errors = cf.parse(SEC, form, stored)
    assert errors == ["CCV Frequency (every N samples) is required."]


def test_nothing_is_coerced():
    stored = _profiles()["EPA_537_1"]
    for name, value in [("f__ccv__frequency", "6.5"), ("f__ccv__recovery_min", "seventy"),
                        ("f__calibration__r2_min", "1.2"), ("f__ccv__frequency", "0")]:
        form = form_of(SEC, stored)
        form[name] = value
        _u, errors = cf.parse(SEC, form, stored)
        assert len(errors) == 1, (name, value, errors)


def test_unchecked_box_is_false_and_blank_technique_removes_the_key():
    stored = _profiles()["FDA_32PFAS"]
    form = form_of(SEC, stored)
    form.pop("f__confirmation__require_confirm_ion_check", None)
    form["f__confirmation__confirm_technique"] = "LC-HRMS"
    after = save(SEC, stored, form)
    assert after["instrument_verification"]["confirmation"]["require_confirm_ion_check"] is False
    form["f__confirmation__confirm_technique"] = ""
    assert "confirm_technique" not in save(SEC, stored, form)["instrument_verification"]["confirmation"]


def test_a_section_save_touches_only_its_own_fields():
    stored = _profiles()["EPA_537_1"]
    form = form_of(SEC, stored)
    form["f__ccv__recovery_max"] = "131"
    form["display_name"] = "hijacked"                          # not this section's
    after = save(SEC, stored, form)
    changed = [c[0] for c in ch.diff(stored, after)]
    assert changed == [("instrument_verification", "ccv", "recovery_max")]
    assert after["instrument_verification"]["sequence"] == stored["instrument_verification"]["sequence"]


def test_the_stamp_moves_only_with_this_section():
    stored = _profiles()["EPA_537_1"]
    other = dict(stored, display_name="renamed")
    assert cf.stamp(SEC, stored) == cf.stamp(SEC, other)
    form = form_of(SEC, stored)
    form["f__ccv__recovery_max"] = "131"
    assert cf.stamp(SEC, stored) != cf.stamp(SEC, save(SEC, stored, form))


CHOICE = cf.Section("t", "T", (), [("g", [cf.Field("unit", "Unit", kind=cf.CHOICE,
                                                   choices=[("ng/L", "ng/L"), ("ng/g", "ng/g")])])])


def test_a_choice_offers_and_accepts_the_stored_value_but_nothing_else():
    stored = {"unit": "µg/L"}
    rows = cf.render(CHOICE, stored)[0]["fields"][0]["choices"]
    assert ("µg/L", "µg/L (stored value)") in rows
    assert cf.parse(CHOICE, {"f__unit": "µg/L"}, stored)[1] == []
    # the browser cannot widen the options by claiming a stored value
    _u, errors = cf.parse(CHOICE, {"f__unit": "ppm", "_stored__f__unit": "ppm"}, stored)
    assert errors


def test_a_unicode_path_is_split_into_keys_not_characters():
    f = cf.Field(u"ccv.frequency", u"x")
    assert f.path == (u"ccv", u"frequency")


# ── wiring guards (the Method Profile editor) ────────────────────────────────

BROWSER = os.path.join(PKG, "browser")


def _read(*parts):
    import io
    with io.open(os.path.join(BROWSER, *parts), encoding="utf-8") as fh:
        return fh.read()


def _method_source(src, name):
    i = src.index("    def %s(" % name)
    j = src.find("\n    def ", i + 1)
    return src[i:j if j != -1 else len(src)]


def test_the_main_form_no_longer_carries_or_parses_a_section():
    """The old handler assigned every instrument criterion unconditionally
    under a marker field. With the fields moved to their own form, either
    half coming back would null them on every Save & Export."""
    assert "instrument_verification_present" not in _read("templates", "method_profile_edit.pt")
    apply_form = _method_source(_read("method_profiles.py"), "_apply_form")
    assert "setdefault(\"instrument_verification\"" not in apply_form


#: The request names the pre-R2 Calibration & CCV inputs used. The form no
#: longer sends them, so a handler that still READS one gets None -- and a
#: None written back nulls a live QC criterion.
OLD_CAL_NAMES = ("cal_r2_min", "cal_force_origin", "cal_point_pct_dev_max",
                 "cal_low_point_pct_dev_max", "conf_rrt_tol_pct", "conf_rt_tol_abs_min",
                 "conf_ion_ratio_tol_pct", "conf_sn_quan_min", "conf_sn_confirm_min",
                 "conf_require_confirm_ion_check", "conf_confirm_technique",
                 "ccv_frequency", "ccv_recovery_min", "ccv_recovery_max",
                 "ccv_low_level_min", "ccv_low_level_max", "is_vs_ical_avg_min",
                 "is_vs_ical_avg_max", "is_vs_last_ccv_min", "is_vs_last_ccv_max", "is_notes")


def test_no_handler_reads_a_retired_request_name():
    import re
    src = _read("method_profiles.py")
    template = _read("templates", "method_profile_edit.pt")
    for name in OLD_CAL_NAMES:
        quoted = re.compile(r"[\"']%s[\"']" % name)
        assert not quoted.search(src), "method_profiles.py reads retired field %s" % name
        assert 'name="%s"' % name not in template, "template still sends %s" % name


def test_every_section_input_names_its_own_form():
    """The section's inputs sit inside profile-form's markup; without form=
    they would be submitted (and dropped) with the main form instead."""
    import re
    macro = _read("templates", "config_form_macros.pt")
    controls = re.findall(r"<(input|select|textarea)\b(.*?)>", macro, re.S)
    assert len(controls) >= 5
    for tag, attrs in controls:
        assert "form cf_form" in attrs, (tag, attrs[:80])


def test_a_section_save_runs_nothing_else_in_the_post_chain():
    """_apply_qc_rules and the surrogate-link sync read fields the section
    form does not carry: reached from a section save they would switch every
    rule off and rewrite the links."""
    post = _method_source(_read("method_profiles.py"), "_handle_post")
    branch = post.index("return self._save_section(")
    for later in ("_apply_form", "_apply_qc_rules"):
        assert branch < post.index(later), later
    save = _method_source(_read("method_profiles.py"), "_save_section")
    for writer in ("_apply_form", "_apply_qc_rules", "surrogate"):
        assert writer not in save, writer
    assert "config_forms.stamp(" in save and "save_profile(" in save



def test_a_method_save_never_writes_the_link_to_the_services():
    """Each method owns its surrogate map (DECISIONS 2026-09-30). Writing it to
    the analysis service, or rebuilding the map from the services, is what made
    one method's edit change every method -- neither may come back into the
    editor. The service field is read only as a suggestion."""
    import re
    src = _read("method_profiles.py")
    assert "_rebuild_surrogate_map" not in src and "_sync_surrogate_links" not in src
    assert not re.search(r"pfas_quant_surrogate[\"']\)\s*\.\s*set\(|fld\.set\(svc", src), (
        "the Method Profile editor writes pfas_quant_surrogate again")
    post = _method_source(src, "_handle_post")
    assert "quant_surrogate" not in post


# ── tables (Reporting Limits) ────────────────────────────────────────────────

RLT = mps.REPORTING_LIMITS


def table_form(table, stored):
    form = {}
    for g in cf.render(table, stored):
        for row in g["rows"]:
            for cell in row["cells"]:
                form[cell["name"]] = cell["value"]
    return form


def _with_limits(mid):
    import copy
    p = copy.deepcopy(_profiles()[mid])
    groups, rows = RLT.rows(p)
    p["reporting_limits"] = {}
    for i, r in enumerate(rows[:12]):
        m, kw = r["key"]
        p["reporting_limits"].setdefault(m, {})[kw] = {"rl": 2.0 + i, "mdl": 0.5 if i % 2 else None}
    return p


def test_an_unchanged_table_save_changes_nothing():
    for mid in _profiles():
        for stored in (_profiles()[mid], _with_limits(mid)):
            after = save(RLT, stored, table_form(RLT, stored))
            assert ch.diff(stored, after) == [], (mid, ch.diff(stored, after)[:3])
            assert cf.stamp(RLT, stored) == cf.stamp(RLT, after)


def test_an_empty_table_stores_nothing_and_changes_nothing():
    stored = _profiles()["FDA_32PFAS"]
    for before in (dict(stored, reporting_limits={}),
                   dict((k, v) for k, v in stored.items() if k != "reporting_limits")):
        after = save(RLT, before, table_form(RLT, before))
        assert after.get("reporting_limits", "absent") == before.get("reporting_limits", "absent")


def test_a_cell_edit_is_exactly_that_cell_and_colon_keys_are_safe():
    stored = _profiles()["FDA_32PFAS"]
    key = next(r["key"] for r in RLT.rows(stored)[1] if ":" in r["key"][1])
    name = cf.cell_name(RLT, key, RLT.columns[0])
    assert ":" not in name and "." not in name and " " not in name
    form = table_form(RLT, stored)
    form[name] = "5"
    assert ch.diff(stored, save(RLT, stored, form)) == [
        (("reporting_limits",), None, {key[0]: {key[1]: {"rl": 5.0, "mdl": None}}})]


def test_mdl_above_rl_is_refused_and_named():
    stored = _profiles()["EPA_537_1"]
    key = RLT.rows(stored)[1][0]["key"]
    form = table_form(RLT, stored)
    form[cf.cell_name(RLT, key, RLT.columns[0])] = "2"
    form[cf.cell_name(RLT, key, RLT.columns[1])] = "3"
    _u, errors = cf.parse(RLT, form, stored)
    assert len(errors) == 1 and "MDL (3.0) is above the RL (2.0)" in errors[0], errors


def test_a_row_not_on_the_page_keeps_its_value():
    """The hand-written save replaced a whole matrix with the rows on the
    page, dropping the RL of an analyte excluded from that matrix."""
    import copy
    stored = copy.deepcopy(_with_limits("EPA_537_1"))
    m, kw = RLT.rows(stored)[1][0]["key"]
    stored.setdefault("analyte_matrix_inclusion", {}).setdefault(kw, {})[m] = False
    after = save(RLT, stored, table_form(RLT, stored))
    assert after["reporting_limits"][m][kw] == stored["reporting_limits"][m][kw]


def test_clearing_a_row_removes_it():
    stored = _with_limits("EPA_537_1")
    m, kw = RLT.rows(stored)[1][0]["key"]
    form = table_form(RLT, stored)
    for c in RLT.columns:
        form[cf.cell_name(RLT, (m, kw), c)] = ""
    after = save(RLT, stored, form)
    assert kw not in after["reporting_limits"].get(m, {})


def test_bad_limits_are_refused():
    stored = _profiles()["EPA_537_1"]
    key = RLT.rows(stored)[1][0]["key"]
    for rl_value in ("abc", "-1"):
        form = table_form(RLT, stored)
        form[cf.cell_name(RLT, key, RLT.columns[0])] = rl_value
        assert cf.parse(RLT, form, stored)[1], rl_value


def test_the_reporting_limits_tab_has_no_hand_written_parser_left():
    src = _read("method_profiles.py")
    template = _read("templates", "method_profile_edit.pt")
    for retired in ("reporting_limits_present", "rlm.", "report_limits.parse_form",
                    "report_limits.merge", "reporting_limit_rows"):
        assert retired not in src, retired
        assert retired not in template, retired


def test_the_matrices_tab_has_no_hand_written_parser_left():
    """The old handler coerced a bad holding time to "unset" and silently
    ignored a save that cleared every matrix; both rules now live, refusing,
    in the declared collection."""
    src = _read("method_profiles.py")
    template = _read("templates", "method_profile_edit.pt")
    for retired in ("matrix_settings_present", "mtx_name.", "mtx_holding.",
                    "matrix_settings_rows", "_matrix_references", "unit_options"):
        assert retired not in src, retired
        assert retired not in template, retired


def test_the_corrections_tab_has_no_hand_written_parser_left():
    """The old handler also re-read salt_adjustment_factors_json and
    matrix_factors_json on EVERY save whose marker was absent -- fields no
    page sends, so the fallback only ever re-stored what was there."""
    src = _read("method_profiles.py")
    template = _read("templates", "method_profile_edit.pt")
    for retired in ("salt_present", "\"matrix_present\"", "salt_factor.", "salt_lot.",
                    "matrix_factor.", "salt_adjustment_factors_json", "matrix_factors_json",
                    "salt_adjustment_rows", "matrix_adjustment_rows"):
        assert retired not in src, retired
        assert retired not in template, retired


def test_every_tab_can_be_opened_by_its_link():
    """A hand-kept list of valid tab ids omitted two tabs, so the redirect
    after saving the Reporting Limits tab opened Rule Toggles -- and the Save
    button then submitted the main form, not the tab's."""
    template = _read("templates", "method_profile_edit.pt")
    assert "var valid = [" not in template
    assert "classList.contains('tab-pane')" in template


def test_the_table_stamp_moves_when_the_rows_change():
    import copy
    stored = _profiles()["EPA_537_1"]
    other = copy.deepcopy(stored)
    m, kw = RLT.rows(stored)[1][0]["key"]
    other.setdefault("analyte_matrix_inclusion", {}).setdefault(kw, {})[m] = False
    assert cf.stamp(RLT, stored) != cf.stamp(RLT, other)
    assert cf.stamp(RLT, stored) == cf.stamp(RLT, dict(stored, display_name="x"))


# ── collections (Matrices & Units) ───────────────────────────────────────────

MTX = mps.MATRICES


def coll_form(coll, stored):
    form = {}
    for row in cf.render(coll, stored):
        for cell in row["cells"]:
            if cell["kind"] == cf.BOOL:
                if cell["checked"]:
                    form[cell["name"]] = "on"
            else:
                form[cell["name"]] = cell["value"]
    return form


def _cell(coll, index, col):
    return cf.collection_name(coll, index, next(c for c in coll.columns if c.path[0] == col))


def test_an_unchanged_matrix_save_changes_nothing():
    for mid, stored in _profiles().items():
        after = save(MTX, stored, coll_form(MTX, stored))
        assert ch.diff(stored, after) == [], (mid, ch.diff(stored, after)[:3])
        for key in ("tight_matrices", "matrix_aliases"):     # absent stays absent
            assert (key in stored) == (key in after), (mid, key)
        assert cf.stamp(MTX, stored) == cf.stamp(MTX, after)


def test_adding_a_matrix_writes_every_setting():
    stored = _profiles()["EPA_537_1"]
    n = len(stored["supported_matrices"])
    form = coll_form(MTX, stored)
    form[_cell(MTX, n, "name")] = "Bottled Water"
    form[_cell(MTX, n, "unit")] = "ng/L"
    form[_cell(MTX, n, "holding_days")] = "14"
    form[_cell(MTX, n, "aliases")] = "bottled, spring water"
    after = save(MTX, stored, form)
    assert after["supported_matrices"][-1] == "Bottled Water"
    assert after["unit_map"]["Bottled Water"] == "ng/L"
    assert after["holding_times"]["Bottled Water"] == 14
    assert after["matrix_aliases"]["Bottled Water"] == ["bottled", "spring water"]


def test_a_bad_holding_time_is_refused_not_stored_as_unset():
    stored = _profiles()["EPA_537_1"]
    for bad in ("0", "-3", "two weeks"):
        form = coll_form(MTX, stored)
        form[_cell(MTX, 0, "holding_days")] = bad
        _rows, errors = cf.parse(MTX, form, stored)
        assert len(errors) == 1 and "Drinking Water: Holding Time" in errors[0], (bad, errors)


def test_removing_a_matrix_with_data_is_refused_and_names_it():
    stored = _profiles()["FDA_32PFAS"]
    form = coll_form(MTX, stored)
    form[_cell(MTX, 0, "name")] = ""                          # remove the first matrix
    _rows, errors = cf.parse(MTX, form, stored)
    assert len(errors) == 1 and "would orphan" in errors[0], errors


def test_a_removal_with_reporting_limits_is_refused():
    import copy
    stored = copy.deepcopy(_profiles()["EPA_537_1"])
    stored.pop("analyte_matrix_inclusion", None)
    stored["reporting_limits"] = {"Surface Water": {"PFOA": {"rl": 2.0, "mdl": None}}}
    form = coll_form(MTX, stored)
    form[_cell(MTX, stored["supported_matrices"].index("Surface Water"), "name")] = ""
    _rows, errors = cf.parse(MTX, form, stored)
    assert errors and "reporting limits for Surface Water" in errors[0], errors


def test_duplicates_nameless_rows_and_an_empty_list_are_refused():
    stored = _profiles()["EPA_537_1"]
    n = len(stored["supported_matrices"])
    form = coll_form(MTX, stored)
    form[_cell(MTX, n, "name")] = "drinking water"            # same, different case
    assert "listed twice" in cf.parse(MTX, form, stored)[1][0]
    form = coll_form(MTX, stored)
    form[_cell(MTX, n, "holding_days")] = "14"                # a value but no name
    assert "give it a name" in cf.parse(MTX, form, stored)[1][0]
    import copy
    bare = copy.deepcopy(stored)
    bare.pop("analyte_matrix_inclusion", None)
    form = coll_form(MTX, bare)
    for i in range(n):
        form[_cell(MTX, i, "name")] = ""
    assert "At least one matrix" in cf.parse(MTX, form, bare)[1][0]


def test_a_stored_unit_outside_the_list_is_kept():
    import copy
    stored = copy.deepcopy(_profiles()["EPA_537_1"])
    stored["unit_map"]["Groundwater"] = "pg/mL"
    after = save(MTX, stored, coll_form(MTX, stored))
    assert after["unit_map"]["Groundwater"] == "pg/mL"


# ── Sample Corrections (salt + matrix factors) ───────────────────────────────

SALT, MF = mps.SALT, mps.MATRIX_FACTORS
LOTS = {"standard_lots": [{"uid": "lotA", "label": "Std A", "lot_number": "A-1"},
                          {"uid": "lotB", "label": "Std B", "lot_number": "B-2", "expired": True}]}


def env_form(table, stored, env=None):
    form = {}
    for g in cf.render(table, stored, env):
        for row in g["rows"]:
            for cell in row["cells"]:
                form[cell["name"]] = cell["value"]
    return form


def env_save(table, stored, form, env=None):
    updates, errors = cf.parse(table, form, stored, env)
    assert not errors, errors
    return cf.apply(table, stored, updates, env)


def test_unchanged_correction_saves_change_nothing():
    """FDA carries a salt row whose lot is NOT in the page's inventory list
    (no env) -- the stored lot is still offered and kept, number included."""
    for mid, stored in _profiles().items():
        for table in (SALT, MF):
            for env in (None, LOTS):
                after = env_save(table, stored, env_form(table, stored, env), env)
                assert ch.diff(stored, after) == [], (mid, table.id, ch.diff(stored, after)[:3])
                for key in ("salt_adjustment_factors", "matrix_factors"):
                    assert (key in stored) == (key in after), (mid, key)


def test_the_default_factor_is_a_placeholder_not_a_value():
    stored = _profiles()["EPA_537_1"]
    cell = cf.render(MF, stored)[0]["rows"][0]["cells"][0]
    assert cell["value"] == "" and cell["placeholder"] == "1.0"


def test_a_salt_factor_and_lot_are_saved_with_the_inventory_lot_number():
    stored = _profiles()["EPA_537_1"]
    key = SALT.rows(stored)[1][0]["key"]
    form = env_form(SALT, stored, LOTS)
    form[cf.cell_name(SALT, key, SALT.columns[0])] = "0.95"
    form[cf.cell_name(SALT, key, SALT.columns[1])] = "lotA"
    after = env_save(SALT, stored, form, LOTS)
    assert after["salt_adjustment_factors"] == [
        {"analyte": key[0], "factor": 0.95, "lot_uid": "lotA", "lot_number": "A-1"}]


def test_factors_out_of_range_are_refused():
    stored = _profiles()["FDA_32PFAS"]
    skey = SALT.rows(stored)[1][0]["key"]
    mkey = MF.rows(stored)[1][0]["key"]
    for table, key, bad in ((SALT, skey, "0"), (SALT, skey, "1.5"), (MF, mkey, "0"),
                            (MF, mkey, "0,95")):
        form = env_form(table, stored)
        form[cf.cell_name(table, key, table.columns[0])] = bad
        assert cf.parse(table, form, stored)[1], (table.id, bad)


def test_a_lot_not_in_the_inventory_or_stored_is_refused():
    stored = _profiles()["EPA_537_1"]
    key = SALT.rows(stored)[1][0]["key"]
    form = env_form(SALT, stored, LOTS)
    form[cf.cell_name(SALT, key, SALT.columns[1])] = "someone-elses-uid"
    assert cf.parse(SALT, form, stored, LOTS)[1]


def test_setting_a_factor_back_to_one_removes_its_row():
    stored = _profiles()["FDA_32PFAS"]
    form = env_form(MF, stored)
    form[cf.cell_name(MF, ("Milk",), MF.columns[0])] = "1"
    after = env_save(MF, stored, form)
    assert "Milk" not in [e["matrix"] for e in after["matrix_factors"]]
    assert len(after["matrix_factors"]) == len(stored["matrix_factors"]) - 1


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
