# -*- coding: utf-8 -*-
"""The equipment chain: a measurement traced to someone else's accredited one.

ISO 17025 §6.5 wants every result to rest on a measurement that is traceable. A
balance verification is itself a measurement, so it establishes nothing unless it
names the reference weight set it was performed with — and that set has to carry
an external metrology laboratory's certificate. §38 built that chain and §39 built
the weight-set and pipette pages; this file pins the part that was left unwired:

    the balance verification FORM did not offer the weight set.

The column and `save_balance_verification(..., weight_set_id=)` both accepted one,
so the chain looked complete from the database side while every verification a lab
actually recorded through the UI traced to nothing.

Writing this found a second, worse defect, pinned in tests/test_template_expressions.py:
`facility_balance.pt` **500'd for every selected balance** from the day it was
written, because `tal:define="i repeat/wp/index"` sat on the same element as
`tal:repeat="wp ..."`. It was invisible because `facility_units` held zero rows, so
no balance could be selected and the form never rendered. Same latency as §40.

Runs against a scratch database via `PFAS_FACILITY_QC_DB`; never touches
`/data/qc/facility_monitoring.db`.
"""
import ast
import importlib.util
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "src", "senaite", "pfas", "facility_qc.py")
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")
BALANCE_PT = os.path.join(BROWSER, "templates", "facility_balance.pt")
PIPETTE_PT = os.path.join(BROWSER, "templates", "facility_pipettes.pt")
VIEWS_PY = os.path.join(BROWSER, "facility_qc.py")


def _fresh_module():
    """A facility_qc bound to its own empty database. Same idiom as
    tests/test_facility_dashboard.py — DB_PATH is read at import time."""
    path = os.path.join(tempfile.mkdtemp(prefix="pfas_eqp_"), "facility.db")
    os.environ["PFAS_FACILITY_QC_DB"] = path
    spec = importlib.util.spec_from_file_location("pfas_facility_qc_eqp", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DB_PATH == path, module.DB_PATH
    module.ensure_schema()
    return module


def _balance(fq, name="AB-1"):
    return fq.save_unit({"unit_type": "balance_analytical", "name": name,
                         "location": "Prep", "serial_number": "SN-1",
                         "sensor_id": ""})


def _good_set(fq, set_id="WS-001", **over):
    data = {"set_id": set_id, "weight_class": "ASTM Class 1",
            "serial_number": "WS-SN", "cal_lab": "Northeast Metrology Lab",
            "cal_lab_accreditation": "ISO/IEC 17025", "cal_cert_number": "NML-1",
            "cal_date": "2026-03-02", "cal_due_date": "2027-03-02",
            "nist_traceable": 1, "active": 1}
    data.update(over)
    return fq.save_weight_set(data)


def _points(fq):
    return [{"nominal_g": n, "label": l, "actual_g": n, "tolerance_g": t}
            for n, l, t in fq.BALANCE_DEFAULTS["balance_analytical"]]


# ── The chain, end to end ────────────────────────────────────────────────────

def test_a_verification_with_a_weight_set_traces_to_the_metrology_lab():
    fq = _fresh_module()
    unit = _balance(fq)
    ws = _good_set(fq)
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq), weight_set_id=ws)

    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert prov["problems"] == [], prov["problems"]
    kinds = [r["type"] for r in prov["records"]]
    assert kinds == ["balance_verification", "weight_set"], kinds
    # The chain must END somewhere outside this laboratory, exactly as a reagent
    # chain ends at its manufacturer's certificate.
    cert = [r["data"] for r in prov["records"] if r["type"] == "weight_set"][0]
    assert cert["cal_lab"] and cert["cal_cert_number"]


def test_a_verification_with_no_weight_set_blocks_and_says_why():
    """The defect this file exists for: what the UI used to produce every time."""
    fq = _fresh_module()
    unit = _balance(fq)
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq))  # no weight_set_id

    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert prov["problems"], "a verification with unknown weights must block"
    joined = " ".join(prov["problems"])
    assert "weight set" in joined and "traced" in joined, joined


def test_an_empty_string_is_not_a_weight_set():
    """`''` is not NULL. A handler that posts the empty string would be counted
    as traced by any `weight_set_id IS NOT NULL` query, which is why the form
    handler uses `(... or None)`."""
    fq = _fresh_module()
    unit = _balance(fq)
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq), weight_set_id="")
    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert prov["problems"], "an empty weight_set_id must not read as traceable"


def test_an_expired_set_fails_as_of_the_day_it_was_used():
    fq = _fresh_module()
    unit = _balance(fq)
    ws = _good_set(fq, cal_due_date="2026-06-30")
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq), weight_set_id=ws)
    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert any("expired" in p for p in prov["problems"]), prov["problems"]


def test_a_set_with_no_external_certificate_establishes_nothing():
    fq = _fresh_module()
    unit = _balance(fq)
    ws = _good_set(fq, cal_lab="", cal_cert_number="")
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq), weight_set_id=ws)
    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert any("metrology laboratory" in p for p in prov["problems"]), \
        prov["problems"]


def test_a_set_that_is_not_nist_traceable_is_reported():
    fq = _fresh_module()
    unit = _balance(fq)
    ws = _good_set(fq, nist_traceable=0)
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq), weight_set_id=ws)
    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert any("NIST" in p for p in prov["problems"]), prov["problems"]


def test_a_pointer_to_a_set_that_does_not_exist_is_not_silence():
    """A dangling id must read as a break, not as an absence."""
    fq = _fresh_module()
    unit = _balance(fq)
    fq.save_balance_verification(unit_id=unit, operator="RH",
                                 verified_date="2026-09-28",
                                 points=_points(fq),
                                 weight_set_id="no-such-set")
    prov = fq.equipment_provenance(unit, "2026-09-28")
    assert prov["problems"], "a dangling weight-set id must block"


def test_gear_that_measures_nothing_owes_no_weight_set():
    """Found against the real released WS-0005: 9 of its 13 equipment entries
    were a mill, a mixer, a centrifuge and a shaker, and the first version of
    equipment_provenance demanded a weight set from each."""
    fq = _fresh_module()
    for ut in ("centrifuge", "vortex_mixer", "shaker", "cryomill"):
        uid = fq.save_unit({"unit_type": ut, "name": ut, "location": "Lab",
                            "serial_number": "", "sensor_id": ""})
        prov = fq.equipment_provenance(uid, "2026-09-28")
        assert prov["problems"] == [], (ut, prov["problems"])


# ── The wiring the chain depends on ──────────────────────────────────────────

def test_the_balance_form_offers_the_weight_set_and_requires_it():
    body = open(BALANCE_PT).read()
    assert 'name="weight_set_id"' in body, \
        "the balance form does not offer the weight set, so a verification " \
        "recorded through the UI traces to nothing (GAPS §39)"
    sel = re.search(r'<select name="weight_set_id"[^>]*>', body).group(0)
    assert "required" in sel, (
        "the field is optional, which builds it and leaves the defect in place: "
        "a verification is a measurement and has no meaning without its "
        "reference standard")
    # Required with nothing to choose has to explain itself, or a lab with no
    # set registered gets an unsubmittable form and no way forward.
    assert "@@pfas-weight-sets" in body


def test_the_balance_handler_reads_it_and_normalises_empty_to_null():
    body = open(VIEWS_PY).read()
    # Slice the BALANCE view first. The first `_save` in the file belongs to
    # PFASFacilityUnitsView, and the first version of this test read that one —
    # it reported the defect still present after the fix was in.
    cls = body.split("class PFASBalanceLogView", 1)[1]
    save = cls.split("def _save(self):", 1)[1].split("def unit(", 1)[0]
    assert "weight_set_id" in save, \
        "the form posts weight_set_id and the handler drops it on the floor"
    assert 'f.get("weight_set_id", "").strip() or None' in save, \
        "an empty string must become NULL, not ''"


def test_neither_log_shows_a_truncated_internal_id():
    """A set is known to a signatory as `WS-001`. The pipette history first
    printed `(weight_set_id or '')[:8]` — a truncated uuid, which identifies the
    set to nobody and reads identically for two sets sharing a prefix."""
    for path in (BALANCE_PT, PIPETTE_PT):
        body = open(path).read()
        assert "weight_set_id') or '')[:8]" not in body, path
        assert "weight_set_label" in body, (
            "%s should resolve the set's label via "
            "browser/facility_qc._weight_set_label" % os.path.basename(path))


# ── The py2 sqlite3.Row key trap ─────────────────────────────────────────────

def _fetch_bound_names(tree):
    """Names bound directly from a `.fetchall()` / `.fetchone()` call.

    Includes `for r in <fetch>` targets, which is where both real defects were.
    """
    names = set()

    def _is_fetch(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("fetchall", "fetchone"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_fetch(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        # `for r in conn.execute(...).fetchall():` binds each ROW, not the list.
        if isinstance(node, ast.For) and _is_fetch(node.iter):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        # `[... for p in <fetch>]`
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            for gen in node.generators:
                if _is_fetch(gen.iter) and isinstance(gen.target, ast.Name):
                    names.add(gen.target.id)
    return names


def test_no_unicode_key_on_a_sqlite_row():
    """A sqlite3.Row may be subscripted only by an int or a BYTE string.

    `facility_qc.py` has `unicode_literals`, so `row["col"]` passes a unicode key
    and raises

        IndexError: Index must be int or string

    Two sites carried this and both were unreachable until data existed:
    `list_balance_verifications` (fixed when the first balance verification was
    recorded — it 500'd the Balance Verification Log) and `_refresh_study_status`
    (still waiting on the first temperature study). Everywhere else in the module
    happens to do `dict(row)` first, which is the idiom this test enforces.

    An AST check, not a regex: the name has to be traced back to the `fetch` that
    bound it.
    """
    src = open(MODULE).read()
    assert "unicode_literals" in src, (
        "if this module ever drops unicode_literals the trap goes away and this "
        "test should go with it")
    tree = ast.parse(src)

    bad = []
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert funcs, "found no functions — the AST walk is broken"
    for fn in funcs:
        # Per FUNCTION, not module-wide. Collecting names across the module gave
        # 20 false positives: `row` is fetch-bound in get_unit() and a plain
        # `dict(u)` in dashboard_summary(), and a name means different things in
        # different scopes.
        fetched = _fetch_bound_names(fn)
        if not fetched:
            continue
        # A name REBOUND through dict(...) is safe from that line on:
        # `ew = dict(ew) if ew else None` is exactly how the real sites were
        # fixed. Line order rather than real flow analysis -- adequate because the
        # conversion belongs immediately after the fetch, and a conversion placed
        # after the reads would be a defect anyway.
        converted = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            calls = [c for c in ast.walk(node.value)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                     and c.func.id == "dict"]
            if not calls:
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in fetched:
                    converted[t.id] = min(converted.get(t.id, node.lineno),
                                          node.lineno)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Subscript):
                continue
            if not (isinstance(node.value, ast.Name)
                    and node.value.id in fetched):
                continue
            idx = node.slice
            # py3.9+ exposes the literal directly; older wraps it in ast.Index.
            if hasattr(ast, "Index") and isinstance(idx, ast.Index):
                idx = idx.value
            if not isinstance(idx, ast.Str):
                continue
            if node.lineno > converted.get(node.value.id, 10 ** 9):
                continue
            bad.append("%s line %d: %s[%r]"
                       % (fn.name, node.lineno, node.value.id, idx.s))
    assert not bad, (
        "a unicode key on a sqlite3.Row raises IndexError under python 2: %s. "
        "Convert the row with dict() first." % bad)


if __name__ == "__main__":
    ok = fail = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fail += 1
                print("FAIL", name, "--", exc)
            except Exception as exc:
                fail += 1
                print("ERROR", name, "--", repr(exc))
            else:
                ok += 1
                print("PASS", name)
    print("{0} passed, {1} failed".format(ok, fail))
    if fail:
        sys.exit(1)
