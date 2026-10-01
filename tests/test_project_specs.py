# -*- coding: utf-8 -*-
"""Project specs: a project's differences from its method (DECISIONS 2026-10-01).

What must hold: no specs = the method exactly; an untouched editor stores
nothing; a stored difference is exactly the cells changed and survives the
lab editing the method's other cells; matrix scopes layer over "All
matrices"; the worker's path patch reproduces the effective profile; and
every looser value -- and only a looser one -- is listed. Real modules, no Zope.
"""
from __future__ import unicode_literals

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, ROOT)
sys.path.insert(0, PKG)

import config_forms as cf                # noqa: E402
import method_profile_sections as mps    # noqa: E402
import project_specs as ps               # noqa: E402
from analyte_reference import NATIVE_ANALYTES   # noqa: E402

SECTIONS = mps.PROJECT_SECTIONS
DUP = mps.DUP_RPD.fields()[0].name


def _profiles():
    path = os.environ.get("PFAS_PROFILES_PATH") or os.path.join(ROOT, "data", "qc", "method_profiles.json")
    with open(path) as fh:
        data = json.load(fh)
    data = data.get("profiles", data)
    # the host copy may predate the store's start-up migrations; run them
    import isomers
    import labelled_standards
    try:
        from pfas_pipeline.analyte_alias import injection_is_names
        injection = sorted(injection_is_names())
    except Exception:                      # Python 2.7: the pipeline is Python 3
        injection = []
    for p in data.values():
        labelled_standards.migrate(p, injection)
        isomers.migrate(p)
    return data


def _env(profiles):
    svcs = dict((r[0], {"role": "analyte", "name": r[1]}) for r in NATIVE_ANALYTES)
    for p in profiles.values():
        for name, e in (p.get("labelled_standards") or {}).items():
            svcs[name] = {"role": "injection_is" if e.get("role") == "injection_is" else "surrogate",
                          "name": name}
    svcs["PFXX"] = {"role": "analyte", "name": "Test extra analyte"}      # in no panel
    svcs["M9PFXX"] = {"role": "surrogate", "name": "M9PFXX"}             # used by no method
    return {"services": svcs}


PROFILES = _profiles()
ENV = _env(PROFILES)


def form_of(section, stored, env=ENV):
    """What the browser submits for an untouched section."""
    form = {}
    if isinstance(section, cf.Table):
        for g in cf.render(section, stored, env):
            for row in g["rows"]:
                for cell in row["cells"]:
                    if cell["kind"] == cf.BOOL:
                        if cell["checked"]:
                            form[cell["name"]] = "on"
                    else:
                        form[cell["name"]] = cell["value"]
    elif isinstance(section, cf.Collection):
        for row in cf.render(section, stored, env):
            for cell in row["cells"]:
                form[cell["name"]] = cell["value"]
    else:
        for g in cf.render(section, stored, env):
            for f in g["fields"]:
                if f["kind"] == cf.MULTI:
                    for o in f["options"]:
                        if o["checked"]:
                            form[o["name"]] = "on"
                elif f["kind"] == cf.BOOL:
                    if f["checked"]:
                        form[f["name"]] = "on"
                else:
                    form[f["name"]] = f["value"]
    return form


def edit(stored, changes, env=ENV):
    """Submit every project section with `changes` {section id: {name: value}}
    on top of the untouched form; returns the new profile."""
    p = copy.deepcopy(stored)
    for s in SECTIONS:
        form = form_of(s, p, env)
        form.update(changes.get(s.id) or {})
        updates, errors = cf.parse(s, form, p, env)
        assert not errors, (s.id, errors)
        p = cf.apply(s, p, updates, env)
    return p


def save(specs, mid, scope, changes, env=ENV):
    """The editor's save: render the scope, apply the edits, store the diff."""
    base, _st = ps.scope_base(PROFILES[mid], specs.get(mid), scope, SECTIONS, env)
    shown, _st = ps._apply_scopes(base, specs.get(mid), [scope], SECTIONS, env)
    new = edit(shown, changes, env)
    return ps.set_scope(specs, mid, scope, ps.scope_patches(base, new, SECTIONS, env))


def tier_cell(p, name, field):
    i = [t["name"] for t in mps.read_tiers(p)].index(name)
    return cf.collection_name(mps.RECOVERY_TIERS, i, [c for c in mps.RECOVERY_TIERS.columns
                                                      if c.path[0] == field][0])


def test_no_specs_is_the_method_exactly():
    for mid, p in PROFILES.items():
        eff, stale = ps.effective(p, {}, p["supported_matrices"][0], env=ENV)
        assert eff == p and stale == [] and ps.profile_patch(p, eff) == [], mid


def test_an_untouched_editor_stores_nothing():
    for mid in PROFILES:
        for scope in [ps.ALL] + PROFILES[mid]["supported_matrices"][:1]:
            assert save({}, mid, scope, {}) == {}, (mid, scope, save({}, mid, scope, {}))


def test_a_difference_is_exactly_the_cell_and_keeps_following_the_method():
    mid = "FDA_32PFAS"
    p = PROFILES[mid]
    specs = save({}, mid, ps.ALL, {"tiers": {tier_cell(p, "tier1_key_tight", "recovery_min"): "70"}})
    assert specs == {mid: {ps.ALL: {"tiers": {"changed": {"tier1_key_tight": {"recovery_min": 70.0}}}}}}, specs
    lab = copy.deepcopy(p)                     # the lab later edits the max on the method
    [t for t in lab["qc_acceptance"]["LFSM"]["tiers"] if t["name"] == "tier1_key_tight"][0]["recovery_max"] = 125.0
    eff, stale = ps.effective(lab, specs[mid], "Eggs", env=ENV)
    t1 = [t for t in eff["qc_acceptance"]["LFSM"]["tiers"] if t["name"] == "tier1_key_tight"][0]
    assert (t1["recovery_min"], t1["recovery_max"]) == (70.0, 125.0) and stale == []
    back = save(specs, mid, ps.ALL, {"tiers": {tier_cell(p, "tier1_key_tight", "recovery_min"): "80"}})
    assert back == {}, back                    # set back to the method's value: nothing stored


def test_a_matrix_scope_layers_over_all_matrices():
    mid = "EPA_537_1"
    specs = save({}, mid, ps.ALL, {"dup": {DUP: "25"}})
    specs = save(specs, mid, "Groundwater", {"dup": {DUP: "35"}})
    rpd = lambda m: ps.effective(PROFILES[mid], specs[mid], m, env=ENV)[0]["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"]   # noqa: E731
    assert (rpd("Drinking Water"), rpd("Groundwater")) == (25.0, 35.0)
    assert specs[mid]["Groundwater"] == {"dup": {DUP: 35.0}}, specs   # measured against "*", not the method
    same = save(save({}, mid, ps.ALL, {"dup": {DUP: "25"}}), mid, "Groundwater", {"dup": {DUP: "25"}})
    assert "Groundwater" not in same[mid], same                       # equal to "*": nothing stored


def test_an_added_analyte_reaches_the_panel_the_links_and_the_limits():
    mid = "EPA_537_1"
    px = cf.cell_name(mps.PANEL_EXTRAS, ("PFXX",), mps.PANEL_EXTRAS.columns[0])
    specs = save({}, mid, ps.ALL, {"px": {px: "on"}})
    eff, _ = ps.effective(PROFILES[mid], specs[mid], None, env=ENV)
    assert "PFXX" in eff["master_analyte_set"] and eff[mps.EXTRAS_KEY] == ["PFXX"]
    assert all(eff["analyte_matrix_inclusion"]["PFXX"].values())
    rl = cf.cell_name(mps.REPORTING_LIMITS, ("Groundwater", "PFXX"),
                      [c for c in mps.REPORTING_LIMITS.columns if c.path[0] == "rl"][0])
    sur = cf.cell_name(mps.SURROGATE_MAP, ("PFXX",), mps.SURROGATE_MAP.columns[0])
    ls_used = cf.cell_name(mps.LABELLED_STANDARDS, ("M9PFXX",), mps.LABELLED_STANDARDS.columns[0])
    ls_role = cf.cell_name(mps.LABELLED_STANDARDS, ("M9PFXX",), mps.LABELLED_STANDARDS.columns[1])
    specs = save(specs, mid, ps.ALL, {"ls": {ls_used: "on", ls_role: "surrogate"},
                                      "sur": {sur: "M9PFXX"}})
    specs = save(specs, mid, "Groundwater", {"rl": {rl: "2"}})
    gw, stale = ps.effective(PROFILES[mid], specs[mid], "Groundwater", env=ENV)
    dw, _ = ps.effective(PROFILES[mid], specs[mid], "Drinking Water", env=ENV)
    assert stale == [], stale
    assert gw["reporting_limits"]["Groundwater"]["PFXX"]["rl"] == 2.0
    assert "PFXX" not in (dw.get("reporting_limits") or {}).get("Groundwater", {}) or \
        dw["reporting_limits"]["Groundwater"]["PFXX"].get("rl") is None
    assert gw["labelled_standards"]["M9PFXX"]["role"] == "surrogate"
    assert [r for r in gw["surrogate_map"] if r["analyte"] == "PFXX"][0]["surrogate_is"] == "M9PFXX"
    assert mps.check_profile(gw) == [], mps.check_profile(gw)
    for kw in PROFILES[mid]["master_analyte_set"]:               # method analytes untouched
        assert kw in gw["master_analyte_set"]
    off = save(specs, mid, ps.ALL, {"px": {px: ""}})              # untick: the analyte goes
    assert "PFXX" not in ps.effective(PROFILES[mid], off[mid], None, env=ENV)[0]["master_analyte_set"]


def test_changing_one_cell_keeps_the_rest_of_that_row():
    """The adapters write a row whole: a project that only relinks a used
    standard must not lose its Used tick or role on the way through."""
    mid = "FDA_32PFAS"
    p = PROFILES[mid]
    grid = p["labelled_standards"]
    name = sorted(n for n, e in grid.items() if e.get("role") == "surrogate")[0]
    target = sorted(n for n, e in grid.items() if e.get("role") == "injection_is")[0]
    ref = cf.cell_name(mps.LABELLED_STANDARDS, (name,), mps.LABELLED_STANDARDS.columns[2])
    specs = save({}, mid, ps.ALL, {"ls": {ref: target if grid[name].get("reference") != target else ""}})
    patch = specs[mid][ps.ALL]["ls"]
    assert set(list(patch.values())[0]) == {mps.LABELLED_STANDARDS.columns[2].name}, patch
    eff, _ = ps.effective(p, specs[mid], None, env=ENV)
    assert name in eff["labelled_standards"], "the standard was dropped"
    assert eff["labelled_standards"][name]["role"] == "surrogate"


def test_blank_unset_and_unticked_compare_equal():
    """Only for comparing: a stored "" and None, or an unticked and an absent
    box, are not a project difference."""
    num, box = mps.DUP_RPD.fields()[0], mps.LABELLED_STANDARDS.columns[0]
    assert ps._same(num, u"", None) and ps._same(box, None, False)
    assert not ps._same(num, 20.0, None) and not ps._same(box, True, None)


def test_isomer_peaks_are_never_offered_as_added_analytes():
    env = {"services": dict(ENV["services"], **{"br-PFOS": {"role": "analyte", "name": "br-PFOS"},
                                                "lr-PFXX": {"role": "analyte", "name": "lr-PFXX"}})}
    for mid, p in PROFILES.items():
        offered = [r["key"][0] for r in mps.extra_rows(p, env)[1]]
        assert "PFXX" in offered, mid
        assert not [k for k in offered if k.lower().startswith(("br-", "lr-"))], (mid, offered)


def test_a_method_analyte_can_never_be_removed_here():
    p = copy.deepcopy(PROFILES["EPA_537_1"])
    kw = p["master_analyte_set"][0]
    out = mps.write_extras(p, {(kw,): {("include",): False}})
    assert kw in out["master_analyte_set"]


def test_the_worker_patch_reproduces_the_effective_profile():
    from pfas_pipeline import method_profiles as mp
    mid = "FDA_32PFAS"
    p = PROFILES[mid]
    px = cf.cell_name(mps.PANEL_EXTRAS, ("PFXX",), mps.PANEL_EXTRAS.columns[0])
    specs = save({}, mid, ps.ALL, {"px": {px: "on"}, "dup": {"rpd_max": "25"},
                                   "tiers": {tier_cell(p, "tier2_linked", "recovery_max"): "140"}})
    eff, _ = ps.effective(p, specs[mid], "Milk", env=ENV)
    data = copy.deepcopy(p)
    mp._apply_profile_patch(data, json.loads(json.dumps(ps.profile_patch(p, eff))))
    assert data == eff
    gone = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    after = {"a": {"b": 1}, "d": 2, "e": {"f": 3}}
    data = copy.deepcopy(gone)
    mp._apply_profile_patch(data, ps.profile_patch(gone, after))
    assert data == after                                              # deletes and adds too


def test_departures_list_looser_values_only():
    mid = "FDA_32PFAS"
    p = PROFILES[mid]
    specs = save({}, mid, ps.ALL, {"tiers": {tier_cell(p, "tier2_linked", "recovery_max"): "140",
                                             tier_cell(p, "tier3_no_std", "recovery_min"): "45"},
                                   "dup": {"rpd_max": "15"}})                  # tighter
    eff, _ = ps.effective(p, specs[mid], None, env=ENV)
    deps = ps.departures(p, eff, mid)
    whats = [(d["what"], d["method"], d["project"]) for d in deps]
    assert ("LFSM recovery max %", "135", "140") in whats, whats
    rows = [d for d in deps if d["what"] == "LFSM recovery max %"]
    keys = mps.key_analytes(p)
    for d in rows:                  # a key analyte is never named for a Tier 1 matrix
        named, where = d["where"].split(" in ", 1)
        if set(named.split(", ")) & keys:
            assert not set(where.split(", ")) & set(p["tight_matrices"]), d
    assert not [w for w in whats if "min" in w[0]]                 # 40 -> 45 is tighter
    assert not [w for w in whats if w[0].startswith("Dup")]        # 20 -> 15 is tighter
    assert all(d["published"] == "published limit not on file" for d in deps)
    loose = save({}, mid, ps.ALL, {"dup": {DUP: "30"}})
    deps = ps.departures(p, ps.effective(p, loose[mid], None, env=ENV)[0], mid)
    assert [d for d in deps if d["what"] == "Dup RPD max %" and d["project"] == "30"]


def test_an_unused_method_standard_is_a_departure():
    mid = "EPA_537_1"
    p = PROFILES[mid]
    name = sorted(n for n, e in p["labelled_standards"].items()
                  if e.get("role") == "surrogate" and
                  not [r for r in p.get("surrogate_map") or [] if r.get("surrogate_is") == n])
    if not name:
        return                                  # every standard quantifies something
    used = cf.cell_name(mps.LABELLED_STANDARDS, (name[0],), mps.LABELLED_STANDARDS.columns[0])
    role = cf.cell_name(mps.LABELLED_STANDARDS, (name[0],), mps.LABELLED_STANDARDS.columns[1])
    specs = save({}, mid, ps.ALL, {"ls": {used: "", role: ""}})
    deps = ps.departures(p, ps.effective(p, specs[mid], None, env=ENV)[0], mid)
    assert [d for d in deps if d["what"] == "Labelled standard %s" % name[0]], deps


def test_a_change_to_a_row_the_method_dropped_is_stale_not_guessed():
    mid = "FDA_32PFAS"
    p = PROFILES[mid]
    specs = save({}, mid, ps.ALL, {"tiers": {tier_cell(p, "tier3_no_std", "recovery_min"): "45"}})
    lab = copy.deepcopy(p)
    lab["qc_acceptance"]["LFSM"]["tiers"] = [t for t in lab["qc_acceptance"]["LFSM"]["tiers"]
                                             if t["name"] != "tier3_no_std"]
    eff, stale = ps.effective(lab, specs[mid], None, env=ENV)
    assert len(stale) == 1 and "tier3_no_std" in stale[0], stale
    assert eff == lab


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        if name == "test_the_worker_patch_reproduces_the_effective_profile" and sys.version_info[0] < 3:
            print("SKIP", name, "(pipeline is Python 3)")
            continue
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
