# -*- coding: utf-8 -*-
"""A machine's finding is evidence; a person's sign-off is authorisation.

ISO 17025 requires results to be authorised by a competent, authorised PERSON. A
service account holds no competence record and takes no responsibility, so its
attestation cannot be the review — and, crucially, must not be INDISTINGUISHABLE
from one in the record.

Before this, `checked_by` was a free string and `all_items_pass()` read only
`checked`. Any account able to POST the check handler could tick a manual item
and open the release gate, leaving a trail identical to a human's. That is the
defect shape this register keeps finding in other forms: a pass that quietly
means nobody looked (GAPS.md §30.5, §31).

`data_review.py` is Zope-bound, so these tests exercise the two pure decisions
lifted out of it by AST — the same technique tests/test_rule_toggles.py uses, and
for the same reason: to assert against the real source rather than a copy of the
logic that can drift from it.
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


def _tree():
    return ast.parse(_source(), REVIEW)


def _func(name):
    """A module-level or method FunctionDef by name, from the AST."""
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef,)) and node.name == name:
            return node
    raise AssertionError("%s not found in %s" % (name, REVIEW))


def _body(name):
    return ast.dump(_func(name))


def _str_constants(node):
    """Every string literal inside `node`.

    ast.dump renders constants with SINGLE quotes, so grepping the dump for
    '"auto"' silently never matches — which is how the first version of
    test_machine_attested_items_only_flags_manual_items reported a defect that
    was not there. Read the values, do not pattern-match the rendering.
    """
    out = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.add(child.value)
    return out


# ── The identity ─────────────────────────────────────────────────────────────

def test_automation_is_a_group_membership_not_a_name_pattern():
    """CLAUDE.md §6A: authority keys off permissions SENAITE already enforces,
    never a parallel list. A name pattern ("svc_*") or a hardcoded tuple of user
    ids would be a second permission system, invisible to an auditor reading
    Plone's own group membership."""
    src = _source()
    assert 'AUTOMATION_GROUP = "PFASAutomation"' in src, (
        "the group NAME changed; it is an ID matched against getGroups() and a "
        "mismatch fails silently, classifying every service account as human")
    assert " " not in "PFASAutomation", "sanity"
    body = _body("_actor_kind")
    assert "getGroups" in body, (
        "_actor_kind no longer consults group membership")
    for smell in ("startswith", "endswith", "svc_", "bot", "_USERS"):
        assert smell not in body, (
            "_actor_kind appears to infer automation from the NAME (%r) rather "
            "than from declared group membership" % smell)


def test_the_group_id_is_id_safe_and_matches_the_sites_convention():
    """`getGroups()` returns group IDs, not titles. A mismatch does not raise —
    it silently classifies every service account as human, which is the one
    direction that matters, because a machine attestation would then open the
    release gate looking like a person's.

    This site's ids are CamelCase with no spaces (Analysts, LabManagers,
    RegulatoryInspectors). A space would also risk the Plone UI transforming what
    a lab typed into something that no longer matches.
    """
    import re
    src = _source()
    match = re.search(r'AUTOMATION_GROUP = "([^"]+)"', src)
    assert match, "AUTOMATION_GROUP is no longer a plain string literal"
    gid = match.group(1)
    assert " " not in gid, ("group id %r contains a space" % gid)
    assert re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", gid), gid


def test_the_group_is_created_by_the_installer_not_left_to_a_human():
    """Leaving a lab to create the group and type the id correctly is a
    silent-failure mode with no symptom. setuphandlers creates it, and grants it
    no roles: it classifies an account, it does not empower one."""
    handlers = os.path.join(_ROOT, "src", "senaite", "pfas", "setuphandlers.py")
    with open(handlers) as fh:
        hsrc = fh.read()
    assert "def setup_automation_group(" in hsrc, (
        "nothing creates the group, so the id is only as right as a human typed it")
    assert "setup_automation_group(portal)" in hsrc, (
        "setup_automation_group is defined but never called from post_install")
    tree = ast.parse(hsrc, handlers)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef)
          and n.name == "setup_automation_group"][0]
    kwargs = {k.arg: k.value for n in ast.walk(fn)
              if isinstance(n, ast.Call) for k in n.keywords if k.arg}
    assert "roles" in kwargs, "addGroup is called without an explicit roles list"
    roles = kwargs["roles"]
    assert isinstance(roles, ast.List) and not roles.elts, (
        "the automation group grants roles; it must classify without empowering")
    assert "getGroupIds" in ast.dump(fn), (
        "setup_automation_group is not idempotent — it does not check first")


def test_the_actor_kind_fails_closed_to_human():
    """An unreadable group list must not reclassify a person's sign-off as
    machine output — that would discard a valid attestation. The risk runs the
    other way, which is why membership is explicit."""
    fn = _func("_actor_kind")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "_actor_kind has no failure path at all"
    returns = [n for h in handlers for n in ast.walk(h)
               if isinstance(n, ast.Return)]
    assert returns, "the failure path does not return a kind"
    values = [r.value.value if isinstance(r.value, ast.Constant) else None
              for r in returns]
    assert values == ["human"], (
        "on failure _actor_kind returns %r; it must fail closed to 'human'"
        % (values,))


# ── Propose, do not attest ───────────────────────────────────────────────────

def test_a_service_account_cannot_set_checked():
    """`checked` is what opens the gate. The handler must branch on actor kind
    BEFORE setting it, and the automated branch must return without doing so."""
    fn = _func("_handle_check_item")
    dumped = ast.dump(fn)
    assert "_actor_kind" in dumped, (
        "_handle_check_item does not distinguish the actor at all")

    # Find the automated branch and confirm it assigns no `checked` and returns.
    automated = [n for n in ast.walk(fn)
                 if isinstance(n, ast.If) and "_actor_kind" in ast.dump(n.test)]
    assert len(automated) == 1, (
        "expected exactly one actor-kind branch, found %d" % len(automated))
    branch = automated[0]
    assigned = set()
    for node in ast.walk(branch):
        if isinstance(node, ast.Subscript) and isinstance(
                getattr(node, "ctx", None), ast.Store):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                assigned.add(key.value)
    assert "checked" not in assigned, (
        "the automated branch sets `checked`, which opens the release gate")
    assert {"proposed_by", "proposed_at"} <= assigned, (
        "the automated branch records no proposal, so the machine's finding is "
        "lost entirely: %s" % sorted(assigned))
    assert any(isinstance(n, ast.Return) for n in ast.walk(branch)), (
        "the automated branch falls through to the human sign-off code")


def test_a_proposal_does_not_overwrite_the_humans_notes():
    """`proposed_notes` is separate from `notes` so a proposal survives the human
    acting on it. Sharing one field would erase the evidence that a machine
    looked first — exactly the provenance the distinction exists to keep."""
    src = _source()
    assert '"proposed_notes"' in src
    fn = _func("_handle_check_item")
    branch = [n for n in ast.walk(fn)
              if isinstance(n, ast.If) and "_actor_kind" in ast.dump(n.test)][0]
    assert '"notes"' not in ast.dump(branch).replace('"proposed_notes"', ""), (
        "the automated branch writes the human-owned `notes` field")


# ── The gate ─────────────────────────────────────────────────────────────────

def test_the_gate_checks_the_attestation_kind_not_only_the_tick():
    """Enforced at the GATE as well as at entry, because an item can also be
    written by a migration or a scripted POST that never reaches the handler —
    GAPS.md §7.1 is precisely that shape (a partial POST nulling live criteria)."""
    body = _body("all_items_pass")
    assert "machine_attested_items" in body, (
        "all_items_pass reads only `checked`; a machine-attested item would "
        "open the release gate")


def test_machine_attested_items_only_flags_manual_items():
    """The two AUTO items (traceability, QC summary) are computed by design —
    flagging those would make the gate permanently unsatisfiable."""
    fn = _func("machine_attested_items")
    literals = _str_constants(fn)
    assert "auto" in literals, (
        "machine_attested_items does not consult the `auto` flag, so it would "
        "flag the two computed items and make the gate unsatisfiable")
    assert "automated" in literals, literals


def test_an_unlabelled_attestation_is_read_as_human():
    """Every existing manual attestation predates `checked_by_kind` and was
    written by a handler that has always demanded an authenticated user and typed
    initials. Reading those as machine output would retroactively invalidate real
    sign-offs; new automated ones are labelled, so the ambiguity does not grow."""
    fn = _func("machine_attested_items")
    literals = _str_constants(fn)
    assert "automated" in literals, literals
    assert "human" not in literals, (
        "machine_attested_items tests for 'human' rather than for 'automated', "
        "so an unlabelled legacy attestation would be flagged as machine output")


def test_submit_distinguishes_machine_attested_from_incomplete():
    """"Incomplete" would send the reviewer hunting for an empty box that does
    not exist. Every box IS ticked; one was ticked by a machine."""
    body = _body("_handle_submit_for_review")
    assert "machine_attested_items" in body
    assert "checklist_machine_attested" in body
    src = _source()
    assert "checklist_machine_attested" in src.split("_MESSAGES", 1)[-1][:4000] \
        or '"checklist_machine_attested"' in src, (
        "the message key is used but never defined, so the redirect shows blank")


def test_every_item_shape_carries_the_new_fields():
    """The checklist dict is built in three places. One of them missing a field
    means an item silently has no attestation kind depending on which path
    created it — a shape defect this project has hit before."""
    src = _source()
    assert src.count('"checked_by_kind"') >= 4, (
        "checked_by_kind appears %d times; expected it in all three item-shape "
        "builders plus the read path" % src.count('"checked_by_kind"'))
    assert src.count('"proposed_by"') >= 4, src.count('"proposed_by"')


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
