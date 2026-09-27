# -*- coding: utf-8 -*-
"""The traceability gate must enforce all three levels, not two.

GAPS §33.2. `_build_traceability_tree` had one branch — the parent-reagent loop,
i.e. level 1, the link that reaches the MANUFACTURER — with no
`else: tree["unresolved"].append(...)`. Since `_compute_traceability_status` keys
solely off `unresolved`, the contrast was stark and was demonstrated live:

    a 252 row naming a nonexistent REAGENT   -> gate FAILED   (correct)
    a standard whose PARENT does not exist   -> gate PASSED   (the defect)

Not a broken gate. A gate with one link missing, which is far harder to notice —
the tree even computed and displayed `unresolved_parents`. Shown, never gated.

`data_review.py` is Zope-bound, so these assert on the AST, the same technique
tests/test_attestation_kind.py and tests/test_rule_toggles.py use. The behavioural
counterpart runs on a live instance and is not repeatable here; see §33 for its
ten probes.
"""
from __future__ import print_function

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
REVIEW = os.path.join(_ROOT, "src", "senaite", "pfas", "browser",
                      "data_review.py")


def _source():
    with open(REVIEW) as fh:
        return fh.read()


def _func(name):
    for node in ast.walk(ast.parse(_source(), REVIEW)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in %s" % (name, REVIEW))


def _appends_to_unresolved(node):
    """Does any statement under `node` append to tree["unresolved"]?"""
    for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr != "append":
            continue
        target = func.value
        if not isinstance(target, ast.Subscript):
            continue
        key = target.slice
        if isinstance(key, ast.Constant) and key.value == "unresolved":
            return True
    return False


def _parent_loop():
    """The `for p in parents:` loop — the level-1 walk."""
    fn = _func("_build_traceability_tree")
    loops = [n for n in ast.walk(fn)
             if isinstance(n, ast.For)
             and isinstance(n.iter, ast.Name) and n.iter.id == "parents"]
    assert len(loops) == 1, (
        "expected exactly one `for p in parents` loop, found %d" % len(loops))
    return loops[0]


# ── Level 1 is gated ─────────────────────────────────────────────────────────

def test_an_unresolvable_parent_reaches_the_unresolved_list():
    """The defect in one assertion. Without this the ISO 17025 §6.6 leaf link is
    the only link in the chain with no enforcement."""
    assert _appends_to_unresolved(_parent_loop()), (
        "the parent-reagent loop does not append to tree['unresolved'], so a "
        "parent naming a reagent that does not exist cannot fail the gate")


def test_a_standard_with_zero_parents_is_caught_outside_the_loop():
    """A loop over an empty list runs zero times, so the fix above cannot catch
    'no parentage at all' — and that case already exists in production
    (PS-FDA-2026-A). It needs its own check."""
    fn = _func("_build_traceability_tree")
    guards = [n for n in ast.walk(fn)
              if isinstance(n, ast.If)
              and isinstance(n.test, ast.UnaryOp)
              and isinstance(n.test.op, ast.Not)
              and isinstance(n.test.operand, ast.Name)
              and n.test.operand.id == "parents"]
    assert guards, (
        "no `if not parents:` guard — a prepared standard with NO parentage "
        "would still pass the gate")
    assert _appends_to_unresolved(guards[0]), (
        "the zero-parent guard does not mark the worksheet unresolved")


def test_every_resolution_branch_can_fail_the_gate():
    """Structural: each place the tree resolves a lot must be able to report
    failure. One branch without it is exactly how §33.2 happened."""
    fn = _func("_build_traceability_tree")
    sources = set()
    for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
        f = call.func
        if not (isinstance(f, ast.Attribute) and f.attr == "append"):
            continue
        if not (isinstance(f.value, ast.Subscript)
                and isinstance(f.value.slice, ast.Constant)
                and f.value.slice.value == "unresolved"):
            continue
        for kw in call.args:
            if isinstance(kw, ast.Dict):
                for k, v in zip(kw.keys, kw.values):
                    if (isinstance(k, ast.Constant) and k.value == "source"
                            and isinstance(v, ast.Constant)):
                        sources.add(v.value)
    for expected in ("252.reagents", "252.standards",
                     "252.extraction_materials", "prepstd.parents"):
        assert expected in sources, (
            "%r never reports an unresolved lot; found %s"
            % (expected, sorted(sources)))


# ── A row with no lot is not evidence ───────────────────────────────────────

def test_has_data_requires_a_row_that_names_a_lot():
    """GAPS §33.10. One 252 row carrying a name and an EMPTY lot made the gate
    pass with zero lots resolved, because the entry is appended outside the
    `if lot:` branch and so could neither resolve nor be reported unresolved."""
    fn = _func("_compute_traceability_status")
    src = ast.dump(fn)
    assert "_with_lots" in src or "lot" in src, (
        "_compute_traceability_status counts bare list lengths; a row with no "
        "lot at all would satisfy it")
    # `len(tree.get("unresolved", []))` is legitimate and must stay; what must
    # NOT come back is counting the ROW lists by bare length.
    row_keys = {"direct_reagents", "direct_standards", "prepared_standards"}
    counted_raw = set()
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "len"):
            continue
        arg = n.args[0] if n.args else None
        if not (isinstance(arg, ast.Call)
                and getattr(arg.func, "attr", "") == "get"):
            continue
        for a in arg.args:
            if isinstance(a, ast.Constant) and a.value in row_keys:
                counted_raw.add(a.value)
    assert not counted_raw, (
        "has_data still counts %s by bare length, so a row carrying a name and "
        "an empty lot satisfies the gate" % sorted(counted_raw))


# ── Archived lots ────────────────────────────────────────────────────────────

def test_archived_reagents_are_excluded_from_the_index():
    """GAPS §33.8. Demonstrated live: archiving a parent left the gate reporting
    resolved=True, so a lot the lab had withdrawn still satisfied traceability.
    Every other consumer filters archived lots; this one did not."""
    fn = _func("_build_lot_indices")
    src = ast.dump(fn)
    assert "_ANN_ARCHIVED_KEY" in src, (
        "_build_lot_indices does not consult the archive flag")


# ── UID-first parent resolution ──────────────────────────────────────────────

def test_a_parent_is_resolved_by_uid_before_its_lot_string():
    """GAPS §33.7. The annotation always carried a `uid` per parent and nothing
    read it, so resolution was by lot-number string alone and a Reagent rename
    broke the level-1 link silently. The repo already does this correctly for
    salt-factor CoA links (D54)."""
    fn = _func("_resolve_parent")
    body = ast.dump(fn)
    assert "uid" in body, "_resolve_parent ignores the stored uid"
    # the lot fallback must survive: every pre-existing parent record has no uid
    assert "lot" in body, (
        "_resolve_parent dropped the lot fallback; every parent record written "
        "before this change carries no usable uid and must keep resolving")
    src = _source()
    i_uid = src.index("uid = (parent.get(\"uid\")")
    i_lot = src.index("lot = (parent.get(\"lot\")")
    assert i_uid < i_lot, "the lot is consulted before the uid"


def test_the_parent_loop_uses_the_resolver():
    """Otherwise the uid-first logic exists and is bypassed — the shape this
    register keeps finding."""
    assert "_resolve_parent" in ast.dump(_parent_loop()), (
        "the parent loop resolves inline instead of calling _resolve_parent")


# ── The chain must reach the CoA ─────────────────────────────────────────────

def test_a_resolved_reagent_reports_whether_it_has_a_coa():
    """The tree terminated at a Reagent URL and never reached the certificate of
    analysis, so it proved inventory membership rather than that the lot is
    certified reference material — which is the point of level 1."""
    assert "has_coa" in ast.dump(_func("_reagent_dict")), (
        "_reagent_dict omits CoA presence, so the chain cannot show whether the "
        "manufacturer lot is certified")


# ── The parentage hierarchy (GAPS §36) ───────────────────────────────────────

PREPSTD = os.path.join(_ROOT, "src", "senaite", "pfas", "browser",
                       "prepared_standards.py")


def _ps_source():
    with open(PREPSTD) as fh:
        return fh.read()


def _ps_func(name):
    for node in ast.walk(ast.parse(_ps_source(), PREPSTD)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in %s" % (name, PREPSTD))


def test_the_parentage_walk_recurses():
    """A lot may be made from another lot made from a CRM. A single-level walk
    would report the intermediate stock as the source."""
    fn = _ps_func("build_parentage")
    assert any(isinstance(n, ast.Call)
               and getattr(n.func, "id", "") == "build_parentage"
               for n in ast.walk(fn)), (
        "build_parentage does not call itself, so parentage stops at one level")


def test_the_walk_is_cycle_safe_and_depth_bounded():
    """A mis-keyed parent pointing at its own descendant must not recurse until
    the request dies. A data-entry error should not take a page down."""
    src = _ps_source()
    assert "MAX_PARENTAGE_DEPTH" in src, "no depth bound on the parentage walk"
    fn = _ps_func("build_parentage")
    dumped = ast.dump(fn)
    assert "_seen" in dumped, "no visited-set, so a cycle would recurse forever"
    assert "circular parentage" in src, (
        "a cycle is not reported to the reader, only silently stopped")


def test_every_branch_ends_in_one_of_three_ways():
    """manufacturer, Type 1 water, or a problem. A branch that stops anywhere
    else is a traceability failure by construction rather than by a check
    somebody remembered to write — which is how level 1 went unenforced."""
    src = _ps_source()
    for const in ("KIND_MANUFACTURER", "KIND_WATER", "KIND_PREPARED",
                  "KIND_UNRESOLVED"):
        assert const in src, const
    fn = _ps_func("build_parentage")
    dumped = ast.dump(fn)
    assert "CATEGORY_INHOUSE_WATER" in dumped, (
        "the walk does not recognise in-house water, so it would demand a "
        "manufacturer for water that has none")


def test_in_house_water_is_checked_against_the_day_of_use():
    """Water produced in house has no manufacturer; the Type 1 QC log for the day
    it was USED is its provenance, and the lab's rule is that an entry must
    always exist for that day."""
    fn = _ps_func("build_parentage")
    dumped = ast.dump(fn)
    assert "get_water_qc_for_date" in dumped, (
        "the water branch does not consult the water QC log")
    assert "used_on" in dumped, (
        "the water check is not keyed on the date of USE, so a working standard "
        "made today from water drawn today would ask about the wrong day")
    # Short fragments: the message wraps across source lines, so a long
    # substring is brittle rather than wrong.
    src = _ps_source()
    assert "water QC entry for that date" in src, (
        "a missing water QC entry is not reported to the reader")
    assert "FAILED" in src, "a water QC entry that FAILED is treated as adequate"


def test_water_is_identified_by_category_not_by_name():
    """Purchased LC-MS water is an ordinary manufactured lot and must keep
    tracing to its supplier. Matching on the word "water" would break that."""
    src = _ps_source()
    fn = ast.dump(_ps_func("build_parentage"))
    assert "CATEGORY_INHOUSE_WATER" in fn
    for smell in ('"water" in', "'water' in", ".lower().find"):
        assert smell not in src, (
            "in-house water appears to be detected by NAME (%r), which would "
            "also catch purchased water" % smell)


def test_the_certificate_and_the_gate_use_the_SAME_walk():
    """They disagreed before: the certificate printed an unresolvable parent as
    fact while the gate passed it, and §33.9 found three resolvers giving three
    answers. One function, one answer."""
    assert "build_parentage" in _ps_source(), "walk missing"
    cert = ast.dump(_ps_func("_render_cert_html"))
    assert "build_parentage" in cert, (
        "the certificate does not walk the chain; it is reprinting the stored "
        "parent record, which is how a fabricated parentage got certified")
    assert "build_parentage" in _source(), (
        "data_review does not use the shared walk, so the gate and the "
        "certificate can disagree again")


def test_the_certificate_states_when_parentage_is_unsubstantiated():
    """A controlled document that cannot substantiate its own parentage has to
    say so on its face — it previously printed a nonexistent lot with the 3-tier
    QA attestation attached and no flag at all."""
    src = _ps_source()
    assert "parentage_problems" in ast.dump(_ps_func("_render_cert_html"))
    assert "NOT FULLY SUBSTANTIATED" in src, (
        "the certificate does not warn when a branch is unresolved")


# ── A specimen CoA establishes nothing (GAPS §37) ────────────────────────────

def test_a_specimen_coa_does_not_establish_traceability():
    """Presence is not sufficiency. Specimen certificates were attached to all 14
    lots so the machinery could be reviewed; if the §6.5 statement counted them,
    the review would have manufactured the very false assurance the subsystem
    exists to prevent."""
    src = _ps_source()
    assert "coa_specimen" in src, (
        "the parentage node does not distinguish a specimen CoA from a real one")
    fn = ast.dump(_ps_func("build_parentage"))
    assert "uploaded_by" in fn or "filename" in fn, (
        "specimen detection does not read the CoA metadata")
    assert "SPECIMEN" in src
    # the §6.5 statement must exclude them
    cert = _ps_func("_render_cert_html")
    dumped = ast.dump(cert)
    assert "coa_specimen" in dumped, (
        "the traceability statement counts a specimen as a certificate")


def test_the_hierarchy_row_says_which_kind_of_coa_it_found():
    src = _ps_source()
    assert "SPECIMEN CoA only" in src, (
        "the hierarchy prints 'CoA on file' for a specimen, which reads as real")


# ── ISO 8601 dates (GAPS §37) ────────────────────────────────────────────────

def _py_files():
    for base, _dirs, files in os.walk(os.path.join(_ROOT, "src", "senaite",
                                                   "pfas")):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_no_human_facing_date_uses_a_locale_dependent_format():
    """Month names and D/M ordering are ambiguous on a document a client and an
    assessor both read: the same string can mean a different day in another
    convention. ISO 8601 everywhere it is DISPLAYED."""
    # Scans the ARGUMENT of each strftime call, from the AST. A raw text scan
    # flags the comment that explains the fix -- which is exactly the mistake
    # tests/test_rule_toggles.py documents having made, and which the first
    # version of this test duly repeated.
    bad = []
    for path in _py_files():
        with open(path) as fh:
            body = fh.read()
        try:
            tree = ast.parse(body, path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") == "strftime"):
                continue
            for arg in node.args:
                if not (isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)):
                    continue
                for pat in ("%B", "%b", "%d/%m/%Y", "%A", "%a"):
                    if pat in arg.value:
                        bad.append("%s: %r" % (os.path.basename(path),
                                               arg.value))
    assert not bad, ("locale-dependent display date formats remain: %s"
                     % sorted(set(bad)))


def test_the_egad_export_keeps_its_required_non_iso_format():
    """The ONE exception, and it must not be 'fixed'. Maine DEP's EGAD EDD
    specifies MM/DD/YYYY; making it ISO would break the state submission. A
    blanket date sweep would do exactly that, so this pins it deliberately."""
    egad = os.path.join(_ROOT, "src", "senaite", "pfas", "egad_builder.py")
    with open(egad) as fh:
        body = fh.read()
    assert '"%m/%d/%Y"' in body, (
        "egad_builder no longer emits MM/DD/YYYY — the EGAD EDD requires it and "
        "a state submission will be rejected without it")


def test_the_certificate_declares_its_date_convention():
    """A reader should not have to infer it."""
    assert "ISO 8601" in _ps_source(), (
        "the certificate does not state which date convention it uses")


# ── ISO 17025 / GMP content on the Certificate of Preparation (GAPS §37) ─────

def test_the_certificate_carries_the_iso17025_identification_fields():
    src = _ps_source()
    for needle, why in (
            ("cert_id", "§7.8.2.1(b) unique identification of the certificate"),
            ("Date of issue", "§7.8.2.1 date of issue"),
            ("lab_header", "§7.8.2.1(a) name and address of the laboratory"),
            ("relates only to", "scope-of-validity statement"),
            ("not a manufacturer certificate", "must not read as a supplier CoA"),
    ):
        assert needle in src, "certificate is missing %s (%s)" % (needle, why)


def test_an_unconfigured_laboratory_identity_is_stated_not_faked():
    """SENAITE ships the Laboratory object titled "Laboratory Information". If
    that were printed as the lab's name the certificate would assert an identity
    nobody configured."""
    src = _ps_source()
    assert "Laboratory Information" in src, (
        "the placeholder lab name is not detected, so it would be printed as if "
        "it were the laboratory's actual name")
    # Short fragment: the message wraps across source lines.
    assert "configured (ISO 17025" in src, (
        "an unconfigured laboratory identity is not stated on the certificate")


def test_the_certificate_does_not_assert_unperformed_verification():
    """It is generated automatically when the lot is recorded. Wording it as
    "Reviewed and verified by <name>" asserted a review that had not happened —
    the same defect shape §32 fixed for the release checklist."""
    src = _ps_source()
    assert "UNSIGNED UNTIL DATED" in src, (
        "the sign-off block does not say it is unsigned")
    assert "Reviewed and verified by" not in src, (
        "the certificate still asserts verification in the past tense")
    assert "Reserved for" in src


# ── Equipment provenance (GAPS §38) ──────────────────────────────────────────

FACILITY = os.path.join(_ROOT, "src", "senaite", "pfas", "facility_qc.py")


def _fq_source():
    with open(FACILITY) as fh:
        return fh.read()


def _fq_func(name):
    for node in ast.walk(ast.parse(_fq_source(), FACILITY)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in %s" % (name, FACILITY))


def test_the_equipment_chain_ends_at_an_external_metrology_lab():
    """The equipment analogue of a reagent's manufacturer CoA: the point where
    the chain leaves this laboratory and becomes someone else's accredited
    measurement. A balance verification is only as good as the weights used, and
    those are calibrated externally."""
    src = _fq_source()
    for needle in ("weight_sets", "cal_lab", "cal_cert_number", "cal_due_date",
                   "nist_traceable"):
        assert needle in src, "weight sets do not record %s" % needle
    fn = ast.dump(_fq_func("equipment_provenance"))
    assert "_weight_set_chain" in fn, (
        "equipment_provenance does not follow the weight set, so a balance "
        "verification traces to nothing")


def test_pipette_calibration_records_internal_and_external():
    """Quarterly in house or by a provider. An internal check is a measurement
    THIS lab made, so it carries its own provenance — the balance and weight set
    it used — while an external one carries a provider and certificate number."""
    src = _fq_source()
    assert "pipette_calibrations" in src
    for needle in ("provider", "cert_number", "balance_unit_id",
                   "weight_set_id", "due_date"):
        assert needle in src, "pipette calibration does not record %s" % needle
    fn = ast.dump(_fq_func("equipment_provenance"))
    assert "external" in fn and "internal" in fn or "balance_unit_id" in fn, (
        "internal and external calibrations are not distinguished")


def test_calibration_is_judged_as_of_the_date_of_use():
    """A run performed while the pipette was in calibration does not stop being
    defensible later. Same rule as the water log and reagent expiry."""
    for name in ("get_pipette_calibration_in_force",
                 "get_balance_verification_for_date", "equipment_provenance"):
        fn = ast.dump(_fq_func(name))
        assert "as_of" in fn or "verified_date" in fn, (
            "%s does not take a date of use" % name)
    src = _fq_source()
    assert "cal_date<=?" in src, (
        "the in-force query does not restrict to calibrations on or before the "
        "date of use, so a LATER calibration would excuse an earlier run")


def test_only_measuring_equipment_owes_a_calibration():
    """A centrifuge, vortex mixer, cryogenic mill or shaker measures nothing and
    has no calibration standard to trace to. Demanding one is a check that can
    never be satisfied, which is worse than no check — and the first version of
    this did exactly that, retroactively failing the already-released WS-0005 on
    a cryogenic mill."""
    src = _fq_source()
    assert "CALIBRATED_UNIT_TYPES" in src, (
        "every piece of equipment is treated as owing a calibration")
    tree = ast.parse(src, FACILITY)
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "CALIBRATED_UNIT_TYPES"
                        for t in node.targets)):
            types = set(ast.literal_eval(node.value))
            break
    else:
        raise AssertionError("CALIBRATED_UNIT_TYPES is not a literal")
    assert types == {"balance_analytical", "balance_prep", "pipette"}, types


def test_unknown_calibration_status_warns_and_does_not_block():
    """An unregistered serial means we cannot tell whether the equipment owed a
    calibration at all. The gap is REGISTRATION; enforcing on it would block a
    release over a vortex mixer. Registering the unit starts enforcement."""
    src = _source()
    assert '"warnings"' in src, (
        "data_review does not separate warnings from blocking problems")
    fq = _fq_source()
    assert 'out["warnings"].append' in fq, (
        "an unregistered unit is reported as a blocking problem")
    # only problems reach the gate
    fn = _func("_build_traceability_tree")
    dumped = ast.dump(fn)
    i_prob = dumped.find('problems')
    assert i_prob != -1
    assert 'entry["warnings"]' in src, "warnings are computed but never kept"


def test_the_equipment_walk_uses_the_documented_dual_read():
    """Worksheet then linked batch, the same order _logbook_json uses. Reading one
    place only is how §33's seeding reported "saw nothing" for the wrong reason —
    and the first version of this walk read the batch alone and found nothing."""
    fn = ast.dump(_func("_build_traceability_tree"))
    assert "_linked_batch" in fn
    assert "extraction_session" in fn, (
        "the equipment walk does not read the extraction session at all")


def test_a_balance_verification_records_the_weight_set_used():
    """Without it the verification traces to nothing — it is a measurement with
    no reference."""
    fn = _fq_func("save_balance_verification")
    args = [a.arg for a in fn.args.args]
    assert "weight_set_id" in args, (
        "save_balance_verification cannot record which weight set was used")
    src = _fq_source()
    assert "weight_set_id," in src
    assert "_ADDED_COLUMNS" in src, (
        "no idempotent migration for the new column, so an instance already "
        "collecting verifications would break or lose them")


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
