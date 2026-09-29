# -*- coding: utf-8 -*-
"""Authorisation: which POST actions are lab configuration, and who may do them.

GAPS §46. Before this, seven configuration surfaces accepted a POST from any
authenticated user. The fix is per ACTION, not per view, because several views
mix configuration with bench work — five of facility_qc's views are the daily
logs, and tightening a module wholesale would have stopped the lab recording
temperatures (§45.8).

Three properties are pinned here, each easy to lose:

  1. **The helper decides correctly**, including failing CLOSED on a broken
     security context or an unknown tier. Tested by behaviour, with a stubbed
     AccessControl.
  2. **The gate tables say what was agreed** — including what must stay OPEN.
     A bench action that becomes manager-only is as much a defect as a config
     action left open: CLAUDE.md §4 requires the bench to be performable by any
     lab user and by a future service account.
  3. **Each view consults its table before doing anything**, and every gated
     name is one the view actually dispatches. A misspelt key in a gate table
     gates nothing and leaves the real action open, silently.

Static/AST for (2) and (3): the view modules need Zope to import.
"""
import ast
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")
PERMS = os.path.join(BROWSER, "perms.py")

CONFIG = "TIER_CONFIG"
SITE_ADMIN = "TIER_SITE_ADMIN"

# (module, view class, gate table, {action: tier}, actions that must stay open)
SPEC = [
    ("facility_qc.py", "PFASFacilityUnitsView", "UNITS_GATES",
     {"save": CONFIG, "delete": CONFIG, "save_defaults": CONFIG,
      "save_api_key": SITE_ADMIN},
     set()),
    ("facility_qc.py", "PFASWeightSetsView", "WEIGHT_SET_GATES",
     {"save": CONFIG, "delete": CONFIG},
     set()),
    ("import_studio.py", "PFASImportStudioView", "STUDIO_GATES",
     {"upload": CONFIG, "save_profile": CONFIG, "retire_profile": CONFIG,
      "reactivate_profile": CONFIG},
     set()),
    ("reagents.py", "PFASReagentsView", "REAGENT_GATES",
     {"save_expiry_defaults": CONFIG, "purge_test": CONFIG},
     {"add", "edit", "open", "status", "delete", "restore", "upload_coa",
      "log_scan"}),
    ("prepared_standards.py", "PFASPrepStandardsView", "PREP_STANDARD_GATES",
     {"delete": CONFIG},
     {"add", "edit", "status"}),
]

# Views that record the lab's daily measurements. None may call the gate.
# Pipette calibration included by decision (2026-09-29): an in-house quarterly
# check is a measurement the lab made, the analogue of the balance log.
BENCH_LOG_VIEWS = [
    ("facility_qc.py", "PFASTemperatureLogView"),
    ("facility_qc.py", "PFASBalanceLogView"),
    ("facility_qc.py", "PFASWaterLogView"),
    ("facility_qc.py", "PFASWasteLogView"),
    ("facility_qc.py", "PFASEyeWashLogView"),
    ("facility_qc.py", "PFASPipetteCalibrationView"),
]


# ── 1. The helper, by behaviour ─────────────────────────────────────────────

class _User(object):
    def __init__(self, roles):
        self._roles = roles

    def getRolesInContext(self, context):
        if self._roles is None:
            raise RuntimeError("broken security context")
        return list(self._roles)


class _Response(object):
    def __init__(self):
        self.status = 200

    def setStatus(self, status):
        self.status = status


class _Request(object):
    def __init__(self):
        self.response = _Response()


def _load_perms(roles):
    """perms.py with AccessControl stubbed to report `roles`."""
    ac = types.ModuleType("AccessControl")
    ac.getSecurityManager = lambda: types.SimpleNamespace(
        getUser=lambda: _User(roles))
    sys.modules["AccessControl"] = ac
    spec = importlib.util.spec_from_file_location("perms_under_test", PERMS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decide(roles, action, gates_by_name):
    perms = _load_perms(roles)
    gates = {k: getattr(perms, v) if v.startswith("TIER_") else v
             for k, v in gates_by_name.items()}
    req = _Request()
    body = perms.deny_gated_action(object(), req, action, gates)
    return body, req.response.status


GATES = {"cfg": CONFIG, "secret": SITE_ADMIN, "typo": "no_such_tier"}


def test_open_action_is_never_refused():
    for roles in ([], ["LabClerk"], None):
        assert _decide(roles, "record", GATES) == (None, 200), roles


def test_config_tier():
    for role in ("Manager", "LabManager", "Owner"):
        assert _decide([role], "cfg", GATES) == (None, 200), role
    for role in ("LabClerk", "Analyst", "Verifier", "Client", "Member"):
        assert _decide([role], "cfg", GATES) == ("Forbidden", 403), role


def test_site_admin_tier_excludes_lab_manager():
    # Decision 2026-09-29: the sensor secret is Manager + Owner only.
    for role in ("Manager", "Owner"):
        assert _decide([role], "secret", GATES) == (None, 200), role
    for role in ("LabManager", "LabClerk"):
        assert _decide([role], "secret", GATES) == ("Forbidden", 403), role


def test_fails_closed():
    # A broken security context is "not permitted", never "permitted".
    assert _decide(None, "cfg", GATES) == ("Forbidden", 403)
    # A tier nobody declared refuses everyone, Manager included.
    assert _decide(["Manager", "Owner"], "typo", GATES) == ("Forbidden", 403)


# ── 2 & 3. The tables, and that each view consults its own first ────────────

def _tree(module):
    with open(os.path.join(BROWSER, module)) as fh:
        return ast.parse(fh.read())


def _gate_table(tree, name):
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            assert isinstance(node.value, ast.Dict), name
            return {k.value: v.id for k, v in zip(node.value.keys,
                                                   node.value.values)}
    raise AssertionError("gate table {0} not found".format(name))


def _class(tree, name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError("class {0} not found".format(name))


def _method(cls, name):
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("{0}.{1} not found".format(cls.name, name))


def _dispatched_actions(func):
    """Every string compared against `action` in `action == "x"` / `in (...)`."""
    out = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == "action"):
            continue
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant):
                out.add(comp.value)
            elif isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List)):
                out.update(e.value for e in comp.elts if isinstance(e, ast.Constant))
    return out


def _gate_calls(func):
    return [n for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "deny_gated_action"]


def _post_branch(func):
    for node in ast.walk(func):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and "method" in ast.dump(node.test.left)
                and any(isinstance(c, ast.Constant) and c.value == "POST"
                        for c in node.test.comparators)):
            return node
    raise AssertionError("no POST branch in {0}".format(func.name))


def test_gate_tables_match_the_agreed_split():
    for module, cls_name, table, expected, must_stay_open in SPEC:
        actual = _gate_table(_tree(module), table)
        assert actual == expected, (table, actual)
        leaked = must_stay_open & set(actual)
        assert not leaked, "{0} gates bench actions {1}".format(table, leaked)


def test_every_gated_action_is_one_the_view_dispatches():
    for module, cls_name, table, expected, _ in SPEC:
        call = _method(_class(_tree(module), cls_name), "__call__")
        missing = set(expected) - _dispatched_actions(call)
        assert not missing, "{0} gates {1}, which {2} never dispatches".format(
            table, missing, cls_name)


def test_each_view_gates_first_in_its_post_branch():
    """The gate is the FIRST statement of the POST branch, so no handler, no
    redirect and no CSRF-disable runs ahead of it, and it is returned."""
    for module, cls_name, table, _, _ in SPEC:
        call = _method(_class(_tree(module), cls_name), "__call__")
        calls = _gate_calls(call)
        assert len(calls) == 1, (cls_name, len(calls))
        assert ast.dump(calls[0].args[3]) == ast.dump(ast.Name(id=table)), (
            "{0} consults the wrong table".format(cls_name))
        branch = _post_branch(call)
        stmts = branch.body
        # facility weight sets reads `action` inside the branch first.
        if (isinstance(stmts[0], ast.Assign)
                and getattr(stmts[0].targets[0], "id", "") == "action"):
            stmts = stmts[1:]
        first, second = stmts[0], stmts[1]
        assert isinstance(first, ast.Assign) and first.value is calls[0], (
            "{0}: gate is not the first statement of the POST branch".format(
                cls_name))
        assert (isinstance(second, ast.If)
                and isinstance(second.body[0], ast.Return)), (
            "{0}: gate result is not returned".format(cls_name))


def test_bench_logs_stay_open():
    for module, cls_name in BENCH_LOG_VIEWS:
        cls = _class(_tree(module), cls_name)
        for node in ast.walk(cls):
            if isinstance(node, ast.Name):
                assert node.id not in ("deny_gated_action", "require_manager",
                                       "require_site_admin"), (
                    "{0} is a bench log and must stay open".format(cls_name))


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
