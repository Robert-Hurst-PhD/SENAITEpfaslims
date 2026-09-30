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
