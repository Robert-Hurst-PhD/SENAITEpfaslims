#!/usr/bin/env python3
"""
Generate WIRING.md — a derived map of what is wired to what in senaite.pfas.

WHY THIS EXISTS. `get_is_list()` read a profile key nothing writes and
returned [] for both EPA methods for four months (GAPS.md §19,
tools/audit_configurable.py's NO PRODUCER check). The hand-maintained docs
(RESOURCE_MAP.md, SYSTEM_AUDIT.md, README.md) cannot prevent the next one of
these because they drift the moment someone edits code without editing prose.
This tool re-derives the wiring from the code itself, every time, so it is
never more stale than the last commit.

THE CENTRAL DESIGN LESSON (commit 7a3099a — read its message). A map keyed on
NAMES ALONE conflates things: this codebase has three unrelated concepts all
called "profile", and two unrelated `_load_profile` functions in different
modules. Every fact below is keyed on SCOPE + NAME (module path + symbol, or
for annotation keys, the literal STRING VALUE — see §1's note on why the key
string, not the Python variable name, is the identity there). Wrappers and
sources are DERIVED by walking the AST, never hardcoded as a name list — a
hardcoded list is exactly what silently lost a real finding in 7a3099a.

SCOPE / POLICY (stated once, here, rather than left silent):
  - Scanned: src/senaite/pfas/**/*.py (the Py2 add-on) and pfas_pipeline/*.py
    (the Py3 worker). tests/ directories are EXCLUDED from producer/consumer
    classification — a test reading a key is not production wiring, and
    counting it would hide a real "no consumer" behind test-only usage.
  - .pyc files, __pycache__ are ignored. Files that fail to parse under
    python3's ast (this tool's runtime, though the target is Python 2.7) are
    skipped and listed at the end of the generated output under "Files
    skipped" — check that section before trusting a "no consumer"/"no
    producer" verdict on a key that might live in one of them.
  - scripts/ and tools/ are NOT scanned for §1: verified by hand (grep) that
    neither touches IAnnotations or any "senaite.pfas.*" annotation key —
    the one hit outside a logger name (tools/generate_synthetic_runs.py's
    docstring) is a MODULE PATH reference, not a key. If either grows an
    IAnnotations call later, add it to ALL_PY_FILES below.
  - §1 (method-profile JSON keys) is NOT re-derived here. That analysis is
    owned by `tools/audit_configurable.py` (DEAD / UNREACHABLE / SPLIT / NO
    PRODUCER) and duplicating it would create the second source of truth this
    exercise exists to avoid. WIRING.md names the command instead.

Run:
    python3 tools/wiring_map.py > WIRING.md
"""
from __future__ import annotations

import ast
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "src", "senaite", "pfas")
PIPELINE_DIR = os.path.join(ROOT, "pfas_pipeline")
PFAS_PREFIX = "senaite.pfas."


def rel(path):
    return os.path.relpath(path, ROOT)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_zcml(path):
    """Read a zcml file with `<!-- ... -->` comments stripped.

    Without this, a viewlet deliberately commented out (browser/configure.zcml
    has one explicitly marked "REMOVED (Round 6)") is regex-matched anyway and
    reported as a live registration — a wiring map that reports a commented-out
    viewlet as active is worse than no map at all.
    """
    return re.sub(r"<!--.*?-->", "", read(path), flags=re.DOTALL)


def iter_py_files(base):
    if not os.path.isdir(base):
        return
    for dirpath, _dirnames, filenames in os.walk(base):
        if "__pycache__" in dirpath:
            continue
        # Normalize so both leading and embedded "tests" path segments match.
        parts = os.path.normpath(dirpath).split(os.sep)
        if "tests" in parts:
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


ALL_PY_FILES = sorted(set(iter_py_files(SRC_DIR)) | set(iter_py_files(PIPELINE_DIR)))

_PARSE_CACHE = {}
_UNPARSEABLE = []


def parse(path):
    if path in _PARSE_CACHE:
        return _PARSE_CACHE[path]
    try:
        tree = ast.parse(read(path), filename=path)
    except SyntaxError:
        tree = None
        _UNPARSEABLE.append(rel(path))
    _PARSE_CACHE[path] = tree
    return tree


# ---------------------------------------------------------------------------
# Module-dotted-name registry, for following `from X import NAME` across files
# ---------------------------------------------------------------------------

def module_name_for(path):
    parts = rel(path).split(os.sep)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODNAME_TO_FILE = {module_name_for(p): p for p in ALL_PY_FILES}
FILE_TO_MODNAME = {p: module_name_for(p) for p in ALL_PY_FILES}


def resolve_import_module(current_modname, node):
    """Absolute dotted module name an `ast.ImportFrom` node refers to."""
    if node.level == 0:
        return node.module
    pkg_parts = current_modname.split(".")[:-1]
    if node.level > 1:
        drop = node.level - 1
        pkg_parts = pkg_parts[:-drop] if len(pkg_parts) >= drop else []
    if node.module:
        return ".".join(pkg_parts + node.module.split("."))
    return ".".join(pkg_parts)


# ---------------------------------------------------------------------------
# Generic AST helpers
# ---------------------------------------------------------------------------

def walk_with_func(node, current_func=None):
    """Every descendant node, tagged with the name of its nearest enclosing
    function (or None at module scope). Used only to label WHERE a constant
    is defined for the duplicate-classification heuristic — never to decide
    what a name MEANS (that stays scope-bounded, see own_nodes below)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child, current_func
            yield from walk_with_func(child, current_func=child.name)
        else:
            yield child, current_func
            yield from walk_with_func(child, current_func)


def own_nodes(scope):
    """Every node in `scope`, in SOURCE ORDER, stopping at nested
    function/class boundaries.

    Same scope-boundary rationale as tools/audit_configurable.py's
    own_nodes: ast.walk descends through nested functions, which would leak
    an `ann` variable bound in one function into an unrelated `ann` (or
    worse, a same-named loop variable) bound in another. A name means what
    it was bound to ONLY inside the scope that bound it.

    SOURCE ORDER matters here (unlike the audit tool's use of this pattern)
    because §1 resolves `key = PREFIX + str(x); ann.get(key)` by replaying
    bindings as it walks — `key = _KEY_PREFIX + str(form_num)` must be seen
    BEFORE `ann.get(key)` two lines later, or the write/read is invisible
    and a genuinely wired key is reported as having no producer.
    """
    def walk(nodelist):
        for node in nodelist:
            yield node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            for _field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, ast.AST):
                            yield from walk([item])
                elif isinstance(value, ast.AST):
                    yield from walk([value])
    return list(walk(getattr(scope, "body", [])))


def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def is_migration_site(path, func_name):
    if "/migrations/" in path.replace(os.sep, "/"):
        return True
    return bool(func_name and func_name.startswith("migrate_"))


# ===========================================================================
# SECTION 1 — ZODB annotation keys
# ===========================================================================

CONST_DEFS = defaultdict(list)       # value -> [(file, varname, lineno, func_or_None)]
FILE_CONSTS = defaultdict(dict)      # file -> {varname: value}   (flattened per file)
NAME_TO_VALUES = defaultdict(set)    # varname -> {values}, across ALL files
IMPORT_EDGES = []                    # (importing_file, local_name, source_file, source_name, lineno)


def pass1_collect_constants():
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        r = rel(path)
        for node, func_name in walk_with_func(tree):
            if isinstance(node, ast.Assign):
                s = const_str(node.value)
                if s is None or not s.startswith(PFAS_PREFIX):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        CONST_DEFS[s].append((r, target.id, node.lineno, func_name))
                        FILE_CONSTS[r][target.id] = s
                        NAME_TO_VALUES[target.id].add(s)


def pass2_follow_imports():
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        r = rel(path)
        modname = FILE_TO_MODNAME[path]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            resolved_mod = resolve_import_module(modname, node)
            target_file = MODNAME_TO_FILE.get(resolved_mod)
            if not target_file:
                continue
            target_consts = FILE_CONSTS.get(rel(target_file), {})
            for alias in node.names:
                if alias.name in target_consts:
                    local = alias.asname or alias.name
                    FILE_CONSTS[r].setdefault(local, target_consts[alias.name])
                    IMPORT_EDGES.append(
                        (r, local, rel(target_file), alias.name, node.lineno))


def is_annotations_expr(expr):
    if isinstance(expr, ast.Call):
        f = expr.func
        name = getattr(f, "id", None) or getattr(f, "attr", None)
        return name == "IAnnotations"
    return False


def raw_value(expr, bindings):
    """A plain string value only — used for the LEFT/BASE of a concat or
    `.format()` call, where a prefix ending in "." (not yet a real key on
    its own) is exactly what we need to see, unlike resolve_key_arg's Name
    branch which deliberately refuses to treat a bare prefix as a key."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        val = bindings.get(expr.id)
        return val if isinstance(val, str) else None
    return None


def resolve_key_arg(expr, bindings):
    """Resolve a key expression to: a str, a list of str (multi-value, from a
    `for key in (K1, K2): ann.get(key)` loop), a ("PREFIX_CONCAT"|"FORMAT",
    template_value) marker, or None (could not resolve).

    `bindings` maps name -> (str | list[str] | tuple marker), and is a LIVE
    snapshot built by replaying assignments in source order as
    pass3_scan_usage walks the scope — see own_nodes' docstring on why order
    matters here.
    """
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, (ast.Name, ast.Attribute)):
        # `self.CORRECTIONS_KEY` where CORRECTIONS_KEY is a class-body
        # constant: pass1 already recorded it in this file's constants under
        # its bare name (pass1 does not distinguish module/class/function
        # scope — see its docstring) — so `expr.attr` resolves the same way
        # a bare Name would.
        name = expr.id if isinstance(expr, ast.Name) else expr.attr
        val = bindings.get(name)
        if val is None:
            return None
        if isinstance(val, (list, tuple)):
            return val
        if val.endswith("."):
            return None  # a bare prefix referenced directly is not a key
        return val
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left_val = raw_value(expr.left, bindings)
        if left_val and left_val.endswith("."):
            return ("PREFIX_CONCAT", left_val)
        return None
    if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "format"):
        base_val = raw_value(expr.func.value, bindings)
        if base_val and "{" in base_val:
            return ("FORMAT", base_val)
        return None
    if isinstance(expr, ast.Call):
        # A call to a KEY-RETURNING WRAPPER (`_rev_key(sop_id): return
        # _ANN_REVISIONS.format(sop_id=sop_id)`) — collect_key_returning_
        # wrappers() stashes its family under a namespaced entry in
        # `bindings` so this generic resolver can find it without a second
        # threading of state through every call site.
        fname = (expr.func.id if isinstance(expr.func, ast.Name) else
                getattr(expr.func, "attr", None))
        if fname:
            wrapped = bindings.get("__wrapper__:" + fname)
            if wrapped is not None:
                return wrapped
    return None


FILE_KEY_RETURN_WRAPPERS = {}   # file -> {func_name: family_marker_tuple}


def collect_key_returning_wrappers():
    """Derive functions whose job is to RETURN a family key, not consume one
    — `_rev_key(sop_id): return _ANN_REVISIONS.format(sop_id=sop_id)`
    (browser/sop_documents.py). Without this, every one of its call sites
    (`ann.get(_rev_key(sop_id))`) resolves to nothing, both SOP families
    report zero evidence, and — this is the part that matters — a family
    with zero evidence looks IDENTICAL to a family that is genuinely never
    read or written. A dead label on live code (`_rev_key`/`_sig_key` are
    exercised on every SOP page view) is exactly the failure mode this
    entire tool exists to prevent, so this gets derived rather than left as
    an §1.3 "unresolved" shrug.

    Scoped per file, like every other wrapper derivation here.
    """
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        consts = FILE_CONSTS.get(rel(path), {})
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in own_nodes(node):
                if isinstance(n, ast.Return) and n.value is not None:
                    keyval = resolve_key_arg(n.value, consts)
                    if isinstance(keyval, tuple):
                        found[node.name] = keyval
                        break
        if found:
            FILE_KEY_RETURN_WRAPPERS[rel(path)] = found


FILE_WRAPPERS = {}   # file -> {func_name: (param_name, param_index, frozenset(kinds))}


def collect_key_wrappers():
    """Derive, per file, functions that wrap an IAnnotations access behind a
    KEY PARAMETER — e.g. `_get_ann(obj, key, default)` doing
    `IAnnotations(obj).get(key, default)` internally. Without this,
    `_set_ann(obj, _ANN_PARENTS, data)` is invisible as a write and a key
    that IS wired reports as `no producer` (this happened for
    `senaite.pfas.prepstd.parent_reagents` during development of this tool —
    exactly the shape 7a3099a's commit message warns about: a wrapper not in
    a hardcoded list silently loses a real finding).

    Scoped PER FILE, never followed across modules — same rule as
    audit_configurable.py's PROFILE_SOURCE_CALLS: missing a cross-file
    wrapper is safer than a same-named wrapper in another file inheriting a
    meaning it doesn't have.
    """
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        wrappers = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = [a.arg for a in node.args.args]
            if len(params) < 2:
                continue
            ann_vars = set()
            nodes = own_nodes(node)
            for n in nodes:
                if isinstance(n, ast.Assign) and is_annotations_expr(n.value):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            ann_vars.add(t.id)

            def is_ann_expr(e, _ann_vars=ann_vars):
                return (isinstance(e, ast.Name) and e.id in _ann_vars) or is_annotations_expr(e)

            # Collect EVERY access kind found, not just the first: the
            # `_get_store_generic(portal, key)` shape does
            # `if key not in ann: ann[key] = PersistentMapping(); return
            # ann[key]` — a lazy-create-and-return getter that is read AND
            # write at every call site (it creates on first use, hands back
            # a live reference either way). Picking only the first match
            # would call every one of its callers "no producer" or "no
            # consumer" depending on which line the walk hit first.
            pname = None
            kinds_found = set()
            for n in nodes:
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in ("get", "pop", "setdefault")
                        and is_ann_expr(n.func.value) and n.args
                        and isinstance(n.args[0], ast.Name)
                        and n.args[0].id in params):
                    kinds_found.add("write" if n.func.attr == "setdefault" else "read")
                    pname = n.args[0].id
                elif (isinstance(n, ast.Subscript) and is_ann_expr(n.value)
                        and isinstance(n.slice, ast.Name)
                        and n.slice.id in params):
                    kinds_found.add("write" if isinstance(n.ctx, ast.Store) else "read")
                    pname = n.slice.id
                elif isinstance(n, ast.Compare):
                    for op, comparator in zip(n.ops, n.comparators):
                        if (isinstance(op, (ast.In, ast.NotIn))
                                and isinstance(n.left, ast.Name)
                                and n.left.id in params
                                and is_ann_expr(comparator)):
                            kinds_found.add("read")
                            pname = n.left.id
            if pname and kinds_found:
                # A method's `self`/`cls` is never passed explicitly at the
                # call site (`self._logbook_json(ws, key)` has 2 call-site
                # args for 3 declared params) — offset the index so the
                # call-site lookup lands on the right argument.
                is_method = params[0] in ("self", "cls")
                call_index = params.index(pname) - (1 if is_method else 0)
                wrappers[node.name] = (pname, call_index, frozenset(kinds_found))
        if wrappers:
            FILE_WRAPPERS[rel(path)] = wrappers


KEY_USES = defaultdict(list)     # literal value -> [(file, line, kind)]
FAMILY_USES = defaultdict(list)  # family template/prefix value -> [(file, line, kind)]
UNRESOLVED = []                  # (file, line, kind, source_text) — could not classify


def record_usage(keyval, path, lineno, kind):
    """Record a read/write, but ONLY for a value that is actually one of our
    keys. This gate matters precisely because §1's detection was broadened
    to not require the receiver to look like an annotations mapping (see
    pass3_scan_usage's comment) — without re-checking the prefix here, an
    unrelated local string (`x = "some_url"; d.get(x)`) resolved through the
    same `bindings` machinery would be recorded as if it were an annotation
    key. `resolve_key_arg`'s plain-Constant branch deliberately returns ANY
    string (it is a generic expression resolver, reused for wrapper-call
    arguments too) — the domain filter belongs here, at the recording
    boundary, not scattered through the generic resolver.
    """
    r = rel(path)
    if keyval is None:
        return False
    if isinstance(keyval, list):
        vals = [v for v in keyval if isinstance(v, str) and v.startswith(PFAS_PREFIX)]
        if not vals:
            return False
        for v in vals:
            KEY_USES[v].append((r, lineno, kind))
        return True
    if isinstance(keyval, tuple):
        _tag, val = keyval
        if not (isinstance(val, str) and val.startswith(PFAS_PREFIX)):
            return False
        FAMILY_USES[val].append((r, lineno, kind))
        return True
    if not (isinstance(keyval, str) and keyval.startswith(PFAS_PREFIX)):
        return False
    KEY_USES[keyval].append((r, lineno, kind))
    return True


def pass3_scan_usage():
    collect_key_returning_wrappers()
    collect_key_wrappers()
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        consts = dict(FILE_CONSTS.get(rel(path), {}))
        for wname, wval in FILE_KEY_RETURN_WRAPPERS.get(rel(path), {}).items():
            consts["__wrapper__:" + wname] = wval
        wrappers = FILE_WRAPPERS.get(rel(path), {})
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module))]
        for scope in scopes:
            nodes = own_nodes(scope)          # SOURCE ORDER — see docstring
            bindings = dict(consts)           # name -> str | list | tuple, replayed live
            ann_vars = set()

            def is_ann_expr(e):
                return (isinstance(e, ast.Name) and e.id in ann_vars) or is_annotations_expr(e)

            for n in nodes:
                # -- update live bindings BEFORE classifying this node, so a
                # key built one line above (`key = PREFIX + str(x)`) is known
                # by the time `ann.get(key)` is reached. --
                if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                        and isinstance(n.targets[0], ast.Name):
                    if is_annotations_expr(n.value):
                        ann_vars.add(n.targets[0].id)
                    else:
                        resolved = resolve_key_arg(n.value, bindings)
                        if resolved is not None:
                            bindings[n.targets[0].id] = resolved
                if isinstance(n, ast.For) and isinstance(n.target, ast.Name):
                    iter_node = n.iter
                    if isinstance(iter_node, (ast.Tuple, ast.List)) and iter_node.elts:
                        vals, ok = [], True
                        for e in iter_node.elts:
                            v = raw_value(e, bindings) or (
                                e.value if isinstance(e, ast.Constant)
                                and isinstance(e.value, str) else None)
                            if isinstance(v, str) and v.startswith(PFAS_PREFIX):
                                vals.append(v)
                            else:
                                ok = False
                                break
                        if ok and vals:
                            bindings[n.target.id] = vals

                # Wrapper call site: `_get_ann(obj, KEY, default)` (plain
                # function) or `self._logbook_json(ws, KEY)` (method — the
                # ATTRIBUTE form, matched on the attribute name since `self`
                # is never explicit at the call site; collect_key_wrappers
                # already adjusted the index for that). The key argument may
                # be resolvable even where the wrapper's OWN internal access
                # could not be — this is the whole point of deriving wrappers.
                wrapper_name = None
                if isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Name) and n.func.id in wrappers:
                        wrapper_name = n.func.id
                    elif isinstance(n.func, ast.Attribute) and n.func.attr in wrappers:
                        wrapper_name = n.func.attr
                if wrapper_name:
                    pname, idx, kinds = wrappers[wrapper_name]
                    arg_expr = n.args[idx] if 0 <= idx < len(n.args) else None
                    if arg_expr is None:
                        for kw in n.keywords:
                            if kw.arg == pname:
                                arg_expr = kw.value
                                break
                    if arg_expr is not None:
                        keyval = resolve_key_arg(arg_expr, bindings)
                        if keyval is not None:
                            for kind in kinds:
                                record_usage(keyval, path, n.lineno, kind)

                # Direct `.get`/`.pop`/`.setdefault`. Gate on the RESOLVED KEY
                # rather than requiring the receiver to be a locally-bound
                # `IAnnotations(...)` name: a pure helper taking the mapping
                # as a parameter (`store_snapshot(store, payload)`, receiving
                # `IAnnotations(ws)` from its caller) never binds `ann =
                # IAnnotations(...)` itself, so gating on the receiver missed
                # a real write (`senaite.pfas.worksheet_criteria_snapshot`
                # during development of this tool). A key argument that
                # resolves to a known `senaite.pfas.*` string is itself
                # sufficient evidence; the receiver check is kept ONLY to
                # decide whether an UNRESOLVED key is worth reporting (an
                # unrelated `some_dict.get(x)` elsewhere must not flood that
                # bucket).
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in ("get", "pop", "setdefault") and n.args):
                    kind = "write" if n.func.attr == "setdefault" else "read"
                    keyval = resolve_key_arg(n.args[0], bindings)
                    if keyval is not None:
                        record_usage(keyval, path, n.lineno, kind)
                    elif is_ann_expr(n.func.value):
                        UNRESOLVED.append((rel(path), n.lineno, kind,
                                           _safe_unparse(n.args[0])))
                elif isinstance(n, ast.Subscript):
                    kind = ("write" if isinstance(n.ctx, ast.Store) else
                            "delete" if isinstance(n.ctx, ast.Del) else "read")
                    keyval = resolve_key_arg(n.slice, bindings)
                    if keyval is not None:
                        record_usage(keyval, path, n.lineno, kind)
                    elif is_ann_expr(n.value):
                        UNRESOLVED.append((rel(path), n.lineno, kind,
                                           _safe_unparse(n.slice)))
                elif isinstance(n, ast.Compare):
                    for op, comparator in zip(n.ops, n.comparators):
                        if isinstance(op, (ast.In, ast.NotIn)):
                            keyval = resolve_key_arg(n.left, bindings)
                            if keyval is not None:
                                record_usage(keyval, path, n.lineno, "read")
                            elif is_ann_expr(comparator):
                                UNRESOLVED.append((rel(path), n.lineno, "read",
                                                   _safe_unparse(n.left)))


def enclosing_func_name(path_rel, lineno):
    """Innermost function containing `lineno` in `path_rel`, or None. Used
    only to decide LEGACY status (see render_evidence) — a key read solely
    by a `migrate_*` function is expected to have no current producer (the
    migration's whole job is reading what an older format wrote), the same
    distinction tools/audit_configurable.py draws for profile keys."""
    full = os.path.join(ROOT, path_rel)
    tree = parse(full)
    if tree is None:
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if start <= lineno <= end and (best is None or (end - start) < best[0]):
                best = (end - start, node.name)
    return best[1] if best else None


def _safe_unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


# ---- family folding ---------------------------------------------------

def build_family_regex(value):
    if "{" in value:
        pattern = re.escape(value)
        pattern = re.sub(r"\\\{[^}]*\\\}", "[^.]+", pattern)
        return re.compile("^" + pattern + "$")
    # prefix style: only the observed concatenation shape in this codebase
    # (PREFIX + str(numeric_id)) — deliberately narrow so an unrelated fixed
    # key sharing the same textual prefix (e.g. "...logbook.pdf_archived")
    # is NOT swept in by a loose "starts with" match.
    return re.compile("^" + re.escape(value) + r"\d+$")


def compute_families():
    families = {}
    for value, defs in CONST_DEFS.items():
        if "{" in value or value.endswith("."):
            families[value] = {
                "value": value,
                "kind": "template" if "{" in value else "prefix",
                "defs": defs,
                "regex": build_family_regex(value),
                "members": [],
            }
    all_literal_values = (set(CONST_DEFS) | set(KEY_USES)) - set(families)
    member_values = set()
    for fam in families.values():
        for v in sorted(all_literal_values):
            if fam["regex"].match(v):
                fam["members"].append(v)
                member_values.add(v)
    return families, member_values


# ---- duplicate classification -----------------------------------------

def compute_duplicates():
    real_dupes = []       # (value, defs) — same value, >=2 non-migration files
    legit_dupes = []       # (value, defs) — same value, includes a migration site
    same_symbol = []       # (varname, {value: [defs]})

    for value, defs in sorted(CONST_DEFS.items()):
        files = {d[0] for d in defs}
        if len(files) < 2:
            continue
        if any(is_migration_site(d[0], d[3]) for d in defs):
            legit_dupes.append((value, defs))
        else:
            real_dupes.append((value, defs))

    for varname, values in sorted(NAME_TO_VALUES.items()):
        if len(values) < 2:
            continue
        by_value = defaultdict(list)
        for value, defs in CONST_DEFS.items():
            for d in defs:
                if d[1] == varname:
                    by_value[value].append(d)
        same_symbol.append((varname, by_value))

    return real_dupes, legit_dupes, same_symbol


def section1():
    pass1_collect_constants()
    pass2_follow_imports()
    pass3_scan_usage()
    families, member_values = compute_families()
    real_dupes, legit_dupes, same_symbol = compute_duplicates()

    all_values = (set(CONST_DEFS) | set(KEY_USES) | set(FAMILY_USES)) - member_values
    standalone = sorted(v for v in all_values if v not in families)

    out = []
    out.append("## 1. ZODB annotation keys\n")
    out.append(
        "`\"senaite.pfas.*\"` strings passed to `IAnnotations(obj)` — the "
        "per-object ZODB store (CLAUDE.md §7). Identity here is the **literal "
        "string value**, not the Python constant name: unlike the `profile` "
        "vocabularies (§0 design note), an annotation key's meaning survives "
        "an import, so a constant imported under a different local name still "
        "resolves to the same fact. Below, WRITE = `ann[k]=`/`.setdefault(k,`, "
        "READ = `ann.get(k)`/`ann[k]`/`k in ann`/`.pop(k)`.\n")
    out.append(
        "Families ({0}), standalone keys ({1}), unresolved dynamic key "
        "expressions ({2} sites — recorded so they are never silently "
        "miscounted as \"no consumer\").\n".format(
            len(families), len(standalone), len(UNRESOLVED)))

    def render_evidence(value, family_write=False, family_read=False):
        defs = CONST_DEFS.get(value, [])
        reads = [u for u in KEY_USES.get(value, []) if u[2] in ("read", "delete")]
        writes = [u for u in KEY_USES.get(value, []) if u[2] in ("write",)]
        lines = []
        if defs:
            lines.append("  - defined: " + ", ".join(
                "`{0}` ({1}:{2})".format(d[1], d[0], d[2]) for d in defs))
        else:
            lines.append("  - defined: (bare literal, no named constant)")
        if writes:
            lines.append("  - written by: " + ", ".join(
                "`{0}:{1}`".format(w[0], w[1]) for w in sorted(set(writes))))
        elif family_write:
            lines.append("  - written by: (covered by the family's dynamic "
                         "concat/format write — see §1.1)")
        if reads:
            lines.append("  - read by: " + ", ".join(
                "`{0}:{1}`".format(r[0], r[1]) for r in sorted(set(reads))))
        elif family_read:
            lines.append("  - read by: (covered by the family's dynamic "
                         "concat/format read — see §1.1)")
        same_line = {(w[0], w[1]) for w in writes} & {(r[0], r[1]) for r in reads}
        if same_line:
            lines.append("  - (same call site appears in both rows above: a "
                         "lazy-create-and-return wrapper — e.g. "
                         "`if key not in ann: ann[key] = {}`, then `return "
                         "ann[key]` — that both creates on first use and "
                         "hands back the live value; every call is both)")
        has_write = bool(writes) or family_write
        has_read = bool(reads) or family_read
        if has_write and has_read:
            state = "wired"
        elif has_write and not has_read:
            state = "no consumer"
        elif has_read and not has_write:
            state = "no producer"
            if reads and all(is_migration_site(f, enclosing_func_name(f, ln))
                             for f, ln in {(u[0], u[1]) for u in reads}):
                state = "legacy — read only by a migration (not a finding)"
        else:
            state = "declared only — never read or written"
        return state, lines

    out.append("### 1.1 Families (templated / prefix-concatenated keys)\n")
    out.append(
        "A family's own state is judged on its DYNAMIC accessors (the "
        "concat/format read or write below) — never left blank: a family "
        "with no evidence line here would be indistinguishable from one "
        "genuinely dead, and these are the highest-traffic keys in the "
        "system (every logbook, every SOP page).\n")
    for value, fam in sorted(families.items()):
        defs = fam["defs"]
        dyn = FAMILY_USES.get(value, [])
        reads = [u for u in dyn if u[2] in ("read", "delete")]
        writes = [u for u in dyn if u[2] == "write"]
        if writes and reads:
            fam_state = "wired"
        elif writes:
            fam_state = "no consumer"
        elif reads:
            fam_state = "no producer"
        else:
            fam_state = "declared only — never read or written dynamically"
        out.append("- **`{0}`** ({1} family) — **{2}** — defined as {3}".format(
            value, fam["kind"], fam_state,
            ", ".join("`{0}` ({1}:{2})".format(d[1], d[0], d[2]) for d in defs)))
        if writes:
            out.append("    - concatenated/formatted write at: " + ", ".join(
                "`{0}:{1}`".format(w[0], w[1]) for w in sorted(set(writes))))
        if reads:
            out.append("    - concatenated/formatted read at: " + ", ".join(
                "`{0}:{1}`".format(r[0], r[1]) for r in sorted(set(reads))))
        if fam["members"]:
            fam_write = any(u[2] == "write" for u in dyn)
            fam_read = any(u[2] in ("read", "delete") for u in dyn)
            out.append("    - concrete instances folded into this family "
                       "(same shape, discovered as literals elsewhere):")
            for m in sorted(fam["members"]):
                state, lines = render_evidence(m, family_write=fam_write,
                                               family_read=fam_read)
                out.append("      - `{0}` — **{1}**".format(m, state))
                for ln in lines:
                    out.append("      " + ln)
        out.append("")

    out.append("### 1.2 Standalone keys ({0})\n".format(len(standalone)))
    by_state = defaultdict(list)
    for value in standalone:
        state, lines = render_evidence(value)
        by_state[state].append((value, lines))
    for state in ("wired", "no consumer", "no producer",
                 "legacy — read only by a migration (not a finding)",
                 "declared only — never read or written"):
        rows = by_state.get(state, [])
        out.append("**{0}** ({1})\n".format(state, len(rows)))
        if not rows:
            out.append("- none\n")
            continue
        for value, lines in rows:
            out.append("- `{0}`".format(value))
            out.extend(lines)
        out.append("")

    if UNRESOLVED:
        out.append("### 1.3 Unresolved dynamic key expressions ({0})\n".format(
            len(UNRESOLVED)))
        out.append(
            "The key argument could not be resolved to a literal. Listed "
            "rather than dropped — a dropped read/write would understate a "
            "key's producers or consumers. Every entry below is the SAME "
            "shape: the generic body of a key-parameter wrapper (`_get_ann`, "
            "`_get_portal_store`, `_get_store_generic`, `_logbook_json` — "
            "see collect_key_wrappers()), scanned like any other function — "
            "inside its OWN definition, `key` is just a parameter with no "
            "fixed value, which is exactly what makes it a reusable "
            "wrapper. This is expected noise, not a gap: each wrapper's "
            "CALL SITES (where `key` is finally bound to something real) "
            "are resolved separately and already counted in §1.1/§1.2 — "
            "that is the whole point of deriving wrappers rather than "
            "reading only direct `IAnnotations(...)` access.\n")
        for f, ln, kind, src in UNRESOLVED[:60]:
            out.append("- `{0}:{1}` ({2}) — `{3}`".format(f, ln, kind, src))
        if len(UNRESOLVED) > 60:
            out.append("- ... and {0} more".format(len(UNRESOLVED) - 60))
        out.append("")

    out.append("### 1.4 Duplicate definitions — §1 rule-3 violations\n")
    out.append(
        "The same key STRING defined as a named constant in more than one "
        "module. Split into real violations and migration-sited "
        "redefinitions, because a migration legitimately re-declares a "
        "legacy key's literal value on its way out — see "
        "`tools/audit_configurable.py`'s LEGACY bucket for the same "
        "distinction applied to profile keys.\n")
    out.append("**Real duplicates ({0})** — no migration involved, both "
               "definitions live production code:\n".format(len(real_dupes)))
    if not real_dupes:
        out.append("- none\n")
    for value, defs in real_dupes:
        out.append("- `{0}` defined in: ".format(value) + ", ".join(
            "`{0}` at `{1}:{2}`{3}".format(
                d[1], d[0], d[2],
                " (in {0}())".format(d[3]) if d[3] else "")
            for d in defs))
    out.append("")
    out.append("**Migration-sited redefinitions ({0})** — legitimate: a "
               "migration reads/writes a legacy store by its old literal "
               "value on the way to the current structure:\n".format(
                   len(legit_dupes)))
    if not legit_dupes:
        out.append("- none\n")
    for value, defs in legit_dupes:
        out.append("- `{0}` defined in: ".format(value) + ", ".join(
            "`{0}` at `{1}:{2}`{3}".format(
                d[1], d[0], d[2],
                " (in {0}())".format(d[3]) if d[3] else "")
            for d in defs))
    out.append("")

    out.append("### 1.5 Same symbol, different key — the inverse hazard\n")
    out.append(
        "A variable NAME reused across modules for a DIFFERENT key string. "
        "Not a bug by itself (each is scoped to its own module), but it is "
        "exactly the naming collision that makes name-only tooling dangerous: "
        "grepping for `_ANN_REGISTRY` without checking which file you're in "
        "answers the wrong question.\n")
    if not same_symbol:
        out.append("- none\n")
    for varname, by_value in same_symbol:
        out.append("- `{0}` means {1} different things:".format(
            varname, len(by_value)))
        for value, defs in sorted(by_value.items()):
            out.append("  - `{0}` — ".format(value) + ", ".join(
                "`{0}:{1}`".format(d[0], d[2]) for d in defs))
    out.append("")

    if IMPORT_EDGES:
        out.append("### 1.6 Cross-module constant imports ({0})\n".format(
            len(IMPORT_EDGES)))
        out.append(
            "Where a key constant is imported by name rather than "
            "redefined — the identity-preserving case §1's design note "
            "above depends on: an import carries the key's meaning with "
            "it, unlike a name-only heuristic over a wrapper function.\n")
        for importer, local, source_file, source_name, ln in IMPORT_EDGES:
            out.append("- `{0}:{1}` imports `{2}` from `{3}` as `{4}`".format(
                importer, ln, source_name, source_file, local))
        out.append("")

    counts = dict(
        families=len(families), standalone=len(standalone),
        unresolved=len(UNRESOLVED), real_dupes=len(real_dupes),
        legit_dupes=len(legit_dupes), same_symbol=len(same_symbol),
    )
    return "\n".join(out), counts


# ===========================================================================
# SECTION 2 — cross-process facts
# ===========================================================================

def grep_lines(path, patterns):
    hits = []
    text = read(path)
    for n, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            if pat.search(line):
                hits.append((rel(path), n, line.strip()))
                break
    return hits


def find_calls(funcname):
    """file:line of every call/def site of `funcname` across the scanned tree."""
    defs, calls = [], []
    pat_def = re.compile(r"^\s*def\s+{0}\s*\(".format(re.escape(funcname)))
    pat_call = re.compile(r"\b{0}\s*\(".format(re.escape(funcname)))
    for path in ALL_PY_FILES:
        text = read(path)
        for n, line in enumerate(text.splitlines(), 1):
            if pat_def.search(line):
                defs.append((rel(path), n))
            elif pat_call.search(line) and not pat_def.search(line):
                calls.append((rel(path), n))
    return defs, calls


def section2():
    out = []
    out.append("## 2. Cross-process facts\n")
    out.append(
        "The Py2 add-on (in-Plone, ZODB) and the Py3 worker (out-of-process) "
        "are one system communicating over files/JSON (CLAUDE.md §7) — this "
        "is where things silently fail to arrive, because nothing short of "
        "running the worker will raise an ImportError for a missing key the "
        "way a same-process read would. Method-profile KEY-level auditing is "
        "owned by `tools/audit_configurable.py` (run "
        "`python3 tools/audit_configurable.py --profiles "
        "data/qc/method_profiles.json`); this section states the file "
        "boundary itself, not its key contents.\n")

    facts = []

    d, c = find_calls("export_profiles_to_file")
    r, _ = find_calls("reload_from_profiles")
    facts.append((
        "`data/qc/method_profiles.json`",
        "add-on (Py2, ZODB-backed method profiles)",
        "worker (Py3, `pfas_pipeline/method_profiles.py`)",
        "writer: `export_profiles_to_file()` — " + ", ".join(
            "`{0}:{1}`".format(*x) for x in c) if c else "writer: none found",
        "reader: `reload_from_profiles()` — defined at " + ", ".join(
            "`{0}:{1}`".format(*x) for x in d) if d else "reader: none found",
    ))

    facts.append((
        "`data/qc/resolved/{batch_id}.json`",
        "add-on (`resolved_criteria_store.export_resolved_criteria`)",
        "worker (`pfas_pipeline/method_profiles.py:reload_from_profiles(batch_id=...)`, "
        "overlays the file on top of the global profile)",
        "writer: `senaite/pfas/resolved_criteria_store.py` "
        "(`export_resolved_criteria`, `write_resolved_file`)",
        "reader: `pfas_pipeline/method_profiles.py` (`reload_from_profiles`, "
        "batch_id branch)",
    ))

    qc_writers = sorted(set(rel(p) for p in ALL_PY_FILES
                            if "pfas_qc_results.db" in read(p)
                            and "PFAS_QC_DB" in read(p)))
    facts.append((
        "`/data/qc/pfas_qc_results.db` (SQLite)",
        "add-on AND worker both read/write directly",
        "same",
        "touched from (add-on side): " + ", ".join(
            "`{0}`".format(f) for f in qc_writers if f.startswith("src/")),
        "touched from (worker side): " + ", ".join(
            "`{0}`".format(f) for f in qc_writers if f.startswith("pfas_pipeline/")),
    ))

    fac_writers = sorted(set(rel(p) for p in ALL_PY_FILES
                             if "facility_monitoring.db" in read(p)))
    facts.append((
        "`/data/qc/facility_monitoring.db` (SQLite)",
        "add-on only",
        "add-on only",
        "touched from: " + ", ".join("`{0}`".format(f) for f in fac_writers),
        "NOT a cross-process fact — no reference to it exists under "
        "pfas_pipeline/. Recorded here to make that absence explicit rather "
        "than assumed.",
    ))

    out.append("| artifact | producer process | consumer process | state |")
    out.append("|---|---|---|---|")
    for name, producer, consumer, wnote, rnote in facts:
        state = "crosses process boundary" if producer != consumer and "only" not in producer else (
            "crosses process boundary" if "same" in consumer else "single-process (add-on only)")
        out.append("| {0} | {1} | {2} | {3} |".format(name, producer, consumer, state))
    out.append("")
    for name, producer, consumer, wnote, rnote in facts:
        out.append("**{0}**".format(name))
        out.append("- {0}".format(wnote))
        out.append("- {0}".format(rnote))
        out.append("")

    return "\n".join(out), {"artifacts": len(facts)}


# ===========================================================================
# SECTION 3 — browser views
# ===========================================================================

ZCML_PAGE_RE = re.compile(
    r'<browser:page\s+((?:[^<]|\n)*?)/>', re.MULTILINE)
ZCML_ATTR_RE = re.compile(r'(\w[\w:]*)\s*=\s*"([^"]*)"')

ZCML_VIEWLET_RE = re.compile(
    r'<browser:viewlet\s+((?:[^<]|\n)*?)/>', re.MULTILINE)
ZCML_VIEWLETMGR_RE = re.compile(
    r'<browser:viewletManager\s+((?:[^<]|\n)*?)/>', re.MULTILINE)
ZCML_ADAPTER_RE = re.compile(
    r'<adapter\s+((?:[^<]|\n)*?)/>', re.MULTILINE)
ZCML_SUBSCRIBER_RE = re.compile(
    r'<subscriber\s+((?:[^<]|\n)*?)/>', re.MULTILINE)


def parse_attrs(blob):
    return dict(ZCML_ATTR_RE.findall(blob))


CLASS_TEMPLATE_CACHE = {}


def find_class_template(dotted_class):
    """Given 'senaite.pfas.browser.method_profiles.PFASMethodProfilesView' or
    a relative '.method_profiles.PFASMethodProfilesView', find a
    ViewPageTemplateFile(...) assigned in that class body."""
    if dotted_class in CLASS_TEMPLATE_CACHE:
        return CLASS_TEMPLATE_CACHE[dotted_class]
    dotted_class = dotted_class.lstrip(".")
    if "." not in dotted_class:
        CLASS_TEMPLATE_CACHE[dotted_class] = None
        return None
    mod_path, cls_name = dotted_class.rsplit(".", 1)
    candidates = [mod_path, "senaite.pfas.browser." + mod_path,
                  "senaite.pfas." + mod_path]
    result = None
    for cand in candidates:
        f = MODNAME_TO_FILE.get(cand)
        if not f:
            continue
        tree = parse(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        val = item.value
                        if (isinstance(val, ast.Call)
                                and getattr(val.func, "id", None) == "ViewPageTemplateFile"
                                and val.args and const_str(val.args[0])):
                            result = (rel(f), item.lineno, const_str(val.args[0]))
                            break
                if result:
                    break
        if result:
            break
    CLASS_TEMPLATE_CACHE[dotted_class] = result
    return result


def section3():
    out = []
    out.append("## 3. Browser views\n")
    out.append(
        "`@@view-name` → class → template, derived from "
        "`browser/configure.zcml` and `browser/overrides.zcml`. Where the "
        "zcml carries no `template=` attribute (most views), the template "
        "is resolved by finding a `ViewPageTemplateFile(...)` class "
        "attribute in the view's own module.\n")

    zcml_files = [
        os.path.join(SRC_DIR, "browser", "configure.zcml"),
        os.path.join(SRC_DIR, "browser", "overrides.zcml"),
    ]
    rows = []
    override_rows = []
    adapter_rows = []
    subscriber_zcml_rows = []
    for zf in zcml_files:
        if not os.path.exists(zf):
            continue
        text = read_zcml(zf)
        is_overrides = zf.endswith("overrides.zcml")
        for m in ZCML_PAGE_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            name = attrs.get("name", "?")
            cls = attrs.get("class", "")
            template = attrs.get("template")
            if not template and cls:
                found = find_class_template(cls)
                if found:
                    template = "{0} (`{1}` at {2}:{3})".format(
                        found[2], "class attr", found[0], found[1])
            row = (name, cls, template or "(none found)", attrs.get("for", "*"),
                  rel(zf))
            rows.append(row)
            if is_overrides:
                override_rows.append(row)
        for m in ZCML_VIEWLET_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            tmpl = attrs.get("template")
            rows.append((attrs.get("name", "?"), attrs.get("class", "(none — template-only viewlet)"),
                        "(viewlet) {0}".format(tmpl) if tmpl else "(viewlet)",
                        attrs.get("for", "*"), rel(zf)))
        for m in ZCML_VIEWLETMGR_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            override_rows.append((attrs.get("name", "?"), attrs.get("class", ""),
                                  "(viewletManager override)", attrs.get("provides", ""),
                                  rel(zf)))
        for m in ZCML_ADAPTER_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            adapter_rows.append((attrs.get("name", "?"), attrs.get("factory", ""),
                                 attrs.get("provides", ""), rel(zf)))
        for m in ZCML_SUBSCRIBER_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            subscriber_zcml_rows.append(attrs)

    out.append("### 3.1 View registry ({0})\n".format(len(rows)))
    out.append("| `@@name` | class | template | for | registered in |")
    out.append("|---|---|---|---|---|")
    for name, cls, template, forr, src in sorted(rows):
        out.append("| `@@{0}` | `{1}` | {2} | `{3}` | `{4}` |".format(
            name, cls, template, forr, src))
    out.append("")

    out.append("### 3.2 Upgrade-risk overrides — replace a core view/adapter "
               "({0})\n".format(len(override_rows) + 2))
    out.append(
        "Registered on `ISenaitePFASLayer` (more specific than core's layer, "
        "so Zope prefers ours without a ZCML conflict — see overrides.zcml's "
        "own comments). Any core signature change here breaks silently on "
        "upgrade rather than raising a conflict error.\n")
    for name, cls, template, forr, src in override_rows:
        out.append("- `@@{0}` (`{1}`, for `{2}`) — {3}".format(
            name, cls, forr, src))
    out.append(
        "- `IReportView`/`IMultiReportView` three-way multiadapters "
        "(`.reportview.PFASSingleReportView` / `PFASMultiReportView`, "
        "`browser/configure.zcml`) — same upgrade-fragility class though "
        "registered in configure.zcml rather than overrides.zcml: "
        "senaite.impress's `PublishView.get_report_view_controller` queries "
        "this 3-way form FIRST and falls back to its own 2-way registration "
        "only if it misses. A signature change to that lookup order breaks "
        "per-result QC qualifier rendering on the CoA (GAPS.md §5) silently.")
    out.append("")

    out.append("### 3.3 Workflow subscribers registered here (cross-ref §4)\n")
    out.append("Declared via `<subscriber ... IAfterTransitionEvent>` in "
               "browser/configure.zcml — see §4 for what each actually "
               "filters on.\n")
    for attrs in subscriber_zcml_rows:
        out.append("- `{0}` — for `{1}`".format(
            attrs.get("handler", "?"), attrs.get("for", "?")))
    out.append("")

    if adapter_rows:
        out.append("### 3.4 Other named adapters ({0})\n".format(len(adapter_rows)))
        for name, factory, provides, src in adapter_rows:
            out.append("- `{0}` → `{1}` (provides `{2}`, {3})".format(
                name or "(unnamed)", factory, provides, src))
        out.append("")

    return "\n".join(out), {
        "views": len(rows), "overrides": len(override_rows) + 2,
        "subscribers_here": len(subscriber_zcml_rows),
    }


# ===========================================================================
# SECTION 4 — workflow subscribers
# ===========================================================================

def find_function(modname_guess_files, func_name="on_after_transition"):
    for f in modname_guess_files:
        tree = parse(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return f, node
    return None, None


def extract_guards(func_node):
    """Early-return `if <compare>: return` guards at the top of the function
    body, rendered via ast.unparse — the semantics are read by a human, not
    re-derived here (that would be re-implementing what the subscriber does,
    not mapping that it exists and what it gates on)."""
    guards = []
    for stmt in func_node.body:
        if (isinstance(stmt, ast.If) and len(stmt.body) == 1
                and isinstance(stmt.body[0], ast.Return)):
            try:
                guards.append(ast.unparse(stmt.test))
            except Exception:
                pass
    return guards


def section4():
    out = []
    out.append("## 4. Workflow subscribers (`IAfterTransitionEvent`)\n")
    out.append(
        "Every one of these fires on EVERY transition of EVERY type in the "
        "site (`for=\"*\"`) — the guard clauses are the ENTIRE reason a "
        "handler only acts on its own transition/type, and a subscriber here "
        "must never raise (raising aborts the transaction that triggered "
        "it). Guard conditions below are `ast.unparse` of each function's "
        "leading `if ...: return` statements, in source order — read, not "
        "re-derived.\n")

    handler_paths = []
    zf = os.path.join(SRC_DIR, "browser", "configure.zcml")
    if os.path.exists(zf):
        text = read_zcml(zf)
        for m in ZCML_SUBSCRIBER_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            h = attrs.get("handler", "")
            if "IAfterTransitionEvent" in attrs.get("for", ""):
                handler_paths.append((h, attrs.get("for", "")))
    zf2 = os.path.join(SRC_DIR, "configure.zcml")
    if os.path.exists(zf2):
        text = read(zf2)
        for m in ZCML_SUBSCRIBER_RE.finditer(text):
            attrs = parse_attrs(m.group(1))
            handler_paths.append((attrs.get("handler", ""), attrs.get("for", "")))

    count = 0
    for handler, forr in handler_paths:
        if "IAfterTransitionEvent" not in forr:
            continue
        count += 1
        mod_part, _dot, func_name = handler.rstrip(".").rpartition(".") \
            if handler.count(".") else ("", "", handler)
        # handler like ".tracking.on_after_transition"
        mod_part = handler.rsplit(".", 1)[0].lstrip(".")
        func_name = handler.rsplit(".", 1)[1]
        candidates = [
            MODNAME_TO_FILE.get("senaite.pfas.browser." + mod_part),
            MODNAME_TO_FILE.get("senaite.pfas." + mod_part),
            MODNAME_TO_FILE.get(mod_part),
        ]
        f = next((c for c in candidates if c), None)
        out.append("### `{0}`\n".format(handler.lstrip(".")))
        if not f:
            out.append("- registered for `{0}` — module not found\n".format(forr))
            continue
        tree = parse(f)
        node = None
        if tree is not None:
            for n in ast.walk(tree):
                if isinstance(n, ast.FunctionDef) and n.name == func_name:
                    node = n
                    break
        if node is None:
            out.append("- `{0}` — function not found\n".format(rel(f)))
            continue
        out.append("- defined at `{0}:{1}`".format(rel(f), node.lineno))
        guards = extract_guards(node)
        if guards:
            out.append("- guards (first matching `return`s out):")
            for g in guards:
                out.append("  - `if {0}: return`".format(g))
        else:
            out.append("- no simple `if ...: return` guard detected at top "
                       "level (see source — logic may be nested)")
        out.append("")

    return "\n".join(out), {"subscribers": count}


# ===========================================================================
# SECTION 5 — Dexterity content types
# ===========================================================================

def section5():
    out = []
    out.append("## 5. Dexterity content types\n")
    out.append(
        "type name → schema interface / class (from "
        "`profiles/default/types/*.xml`) → the portal folder instances "
        "actually live in, derived by finding every `invokeFactory(\"Type\", "
        "...)` call and tracing its receiver variable back to a `portal[...]` "
        "/ `portal.get(...)` binding in the SAME function.\n")

    types_dir = os.path.join(SRC_DIR, "profiles", "default", "types")
    type_info = {}
    if os.path.isdir(types_dir):
        for name in sorted(os.listdir(types_dir)):
            if not name.endswith(".xml"):
                continue
            text = read(os.path.join(types_dir, name))
            type_name = name[:-4]
            schema = re.search(r'name="schema">([^<]*)<', text)
            klass = re.search(r'name="klass">([^<]*)<', text)
            type_info[type_name] = {
                "schema": schema.group(1) if schema else "?",
                "klass": klass.group(1) if klass else "?",
                "folders": set(),
                "sites": [],
            }

    def folder_id_from_expr(expr, base_name):
        """`<base_name>["pfas_x"]` or `<base_name>.get("pfas_x")` -> "pfas_x"."""
        if isinstance(expr, ast.Subscript) and getattr(expr.value, "id", None) == base_name:
            key = getattr(expr.slice, "value", expr.slice)
            return const_str(key) or const_str(expr.slice)
        if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
                and expr.func.attr == "get"
                and getattr(expr.func.value, "id", None) == base_name
                and expr.args):
            return const_str(expr.args[0])
        return None

    # Derive per-file folder-lookup wrappers (`_get_folder(portal): return
    # portal.get("pfas_prep_logbooks")`) the same way §1 derives annotation
    # accessor wrappers — every content type here is fetched through one of
    # these, not through a bare `portal["pfas_x"]` at the call site, so
    # without this every folder would report "(unresolved receiver)".
    file_folder_wrappers = {}
    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        wrappers = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = [a.arg for a in node.args.args]
            if len(params) != 1:
                continue
            base = params[0]
            local_folder_of = {}
            found_id = None
            for n in own_nodes(node):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                        and isinstance(n.targets[0], ast.Name):
                    fid = folder_id_from_expr(n.value, base)
                    if fid:
                        local_folder_of[n.targets[0].id] = fid
                if isinstance(n, ast.Return) and n.value is not None:
                    fid = folder_id_from_expr(n.value, base)
                    if not fid and isinstance(n.value, ast.Name):
                        fid = local_folder_of.get(n.value.id)
                    if fid:
                        found_id = fid
            if found_id:
                wrappers[node.name] = found_id
        if wrappers:
            file_folder_wrappers[rel(path)] = wrappers

    for path in ALL_PY_FILES:
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            wrappers_here = file_folder_wrappers.get(rel(path), {})
            folder_of = {}
            for n in own_nodes(node):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                        and isinstance(n.targets[0], ast.Name):
                    val = n.value
                    folder_id = folder_id_from_expr(val, "portal")
                    if not folder_id and isinstance(val, ast.Call) \
                            and isinstance(val.func, ast.Name) \
                            and val.func.id in wrappers_here:
                        folder_id = wrappers_here[val.func.id]
                    if folder_id:
                        folder_of[n.targets[0].id] = folder_id
            for n in own_nodes(node):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "invokeFactory" and n.args):
                    type_name = const_str(n.args[0])
                    if type_name not in type_info:
                        continue
                    recv = getattr(n.func.value, "id", None)
                    folder_id = folder_of.get(recv, "(unresolved receiver `{0}`)".format(recv))
                    type_info[type_name]["folders"].add(folder_id)
                    type_info[type_name]["sites"].append((rel(path), n.lineno))

    out.append("| type | schema | klass | folder(s) instances live in | example site |")
    out.append("|---|---|---|---|---|")
    orphans = []
    for type_name, info in sorted(type_info.items()):
        if info["folders"]:
            folders = ", ".join(sorted(info["folders"]))
        else:
            folders = "**ORPHAN** — no `invokeFactory(\"{0}\", ...)` call " \
                     "anywhere in the scanned tree".format(type_name)
            orphans.append(type_name)
        site = "{0}:{1}".format(*info["sites"][0]) if info["sites"] else "-"
        out.append("| `{0}` | `{1}` | `{2}` | {3} | `{4}` |".format(
            type_name, info["schema"], info["klass"], folders, site))
    out.append("")
    if orphans:
        out.append(
            "**{0} type(s) registered (types.xml FTI + schema/klass) but "
            "never instantiated anywhere this tool scanned**: {1}. For "
            "`EnvironmentalReading`, this is consistent with CLAUDE.md §7 — "
            "facility QC readings are documented as living in SQLite "
            "(`/data/qc/facility_monitoring.db`), not ZODB — which makes "
            "this Dexterity type plausibly vestigial from an earlier design "
            "rather than a live content type. Worth a human decision "
            "(remove the FTI, or find the missing call site), not asserted "
            "here.\n".format(len(orphans), ", ".join("`{0}`".format(o) for o in orphans)))
    return "\n".join(out), {"types": len(type_info), "orphans": len(orphans)}


# ===========================================================================
# Assembly
# ===========================================================================

HEADER = """\
# WIRING.md — generated wiring map (DO NOT EDIT)

Generated by `python3 tools/wiring_map.py > WIRING.md`. Regenerate after any
change to annotation keys, browser views, workflow subscribers, or content
types — this file is trustworthy only as long as it is regenerated, never
hand-patched (see CONFIG_AUDIT.md's own header for the same rule, and
GAPS.md's verification block for the standing command).

Read this FIRST for "what is wired to what." `RESOURCE_MAP.md` and
`SYSTEM_AUDIT.md` are rationale and history — how a decision was reached and
why a defect happened — not a current reference; they are not regenerated and
they drift. Method-profile JSON keys (DEAD / UNREACHABLE / SPLIT / NO
PRODUCER) are owned by `tools/audit_configurable.py`, not this file — see §2's
note.

No generation timestamp is printed here on purpose (same choice
`audit_configurable.py --format md` makes for CONFIG_AUDIT.md): a timestamp
would make every re-run of GAPS.md's verification chain diff this file even
when nothing changed, training reviewers to ignore its diffs. Diff it for
real content changes only.
"""


def main():
    parts = []
    counts = {}
    for fn in (section1, section2, section3, section4, section5):
        text, c = fn()
        parts.append(text)
        counts[fn.__name__] = c

    body = HEADER
    body += "\n" + "\n".join(parts)

    if _UNPARSEABLE:
        body += "\n## Files skipped (failed to parse)\n\n"
        for f in _UNPARSEABLE:
            body += "- `{0}`\n".format(f)

    sys.stdout.write(body)

    print("--- wiring_map.py summary ---", file=sys.stderr)
    for name, c in counts.items():
        print("{0}: {1}".format(name, c), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
