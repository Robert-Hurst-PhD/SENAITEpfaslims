#!/usr/bin/env python3
"""
Audit CLAUDE.md §1.1 — "configurable, not hardcoded" — across the codebase.

A lab running 10,000 samples a year changes acceptance limits, adds matrices and
retires reagent lots constantly. Every one of those has to be a UI edit, not a
code change. This session found EIGHT separate instances of the same failure
shape, so the point of this tool is that the ninth is caught by running it
rather than by someone tripping over a wrong result.

Three checks, each reporting file:line so a human can judge:

  DEAD CONFIG        a profile key the UI writes that no engine code reads.
                     Editing it changes nothing. (The CCV window did this: the
                     editor saved 72-128% while runs used the nested 70-130%.)

  UNREACHABLE        a key the engine reads that no UI writes. It is a
                     configuration in name only — the lab cannot change it.
                     (recovery_tiers, matrix_aliases.)

  SPLIT KEY          the same name at both a flat and a nested path, the exact
                     residue that migrate_profile_structure left behind and
                     that four separate defects came out of.

Plus a scan for HARDCODED LAB VALUES: numeric or list literals standing in for
something a lab would want to change — acceptance limits, analyte membership,
matrix names, agency codes.

    python3 tools/audit_configurable.py
    python3 tools/audit_configurable.py --profiles /data/qc/method_profiles.json
    python3 tools/audit_configurable.py --format md > CONFIG_AUDIT.md
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIRS = ["pfas_pipeline"]
UI_DIRS = [os.path.join("src", "senaite", "pfas", "browser")]
STORE_DIRS = [os.path.join("src", "senaite", "pfas")]
ALL_DIRS = ENGINE_DIRS + STORE_DIRS

# Keys that are structural containers rather than settings.
CONTAINER_KEYS = {
    "instrument_verification", "qc_acceptance", "extraction_corrections",
    "method_id", "display_name", "description",
    "_seeded",  # internal "has this profile been initialised" flag
}

# Keys the system DERIVES and must keep deriving. They are read but never
# hand-edited on purpose: master_analyte_set comes from the Method's SENAITE
# services, matrix_uid_map from the Sample Type objects. A UI writer for these
# would create the second source of truth §1.3 forbids. Recorded here with the
# deriving call site so "unreachable" keeps meaning "the lab is locked out".
DERIVED_KEYS = {
    "master_analyte_set": "method_profile_store.py:1239 — from the Method's services",
    "display_analyte_set": "method_profile_store.py:1253 — from the master set",
    "matrix_uid_map": "method_profile_store.py:1117 — from the Sample Type UIDs",
}

# A literal that looks like a lab value rather than a programming constant.
# 0/1/2 and the like are excluded: they are almost always indices or flags.
LAB_NUMBER = re.compile(r"(?<![\w.])(\d{2,3}\.\d+|0\.9\d{1,3}|1\.\d{2,})(?![\w.])")

HARDCODED_HINTS = [
    (re.compile(r'\.get\(\s*["\'](\w+)["\']\s*,\s*([0-9]+\.[0-9]+)\s*\)'),
     "acceptance value inlined as a fallback"),
    (re.compile(r'^\s*_?[A-Z][A-Z0-9_]{3,}\s*=\s*(?:frozenset\()?[\{\[]'),
     "module-level table"),
    (re.compile(r'default\s*=\s*["\'][A-Z]{2,5}["\']'),
     "agency / matrix code inlined"),
]

# A module-level table is CODE STRUCTURE, not a lab value, when it describes
# how to parse or address data rather than what the lab has decided. Reporting
# these drowns the real findings: the first run produced 205 hits, most of them
# column vocabularies nobody would ever want to edit.
STRUCTURAL_TABLES = re.compile(
    r"^_?(?:.*_)?(?:COLS?|COLUMNS?|COL_MAP|FIELDS?|CANDIDATES|ROLE_MAP|"
    r"ND_VALUES|FLOAT_COLS|QUALIFIER_TOKENS|SCHEMA|PATTERNS_INTERNAL|"
    r"UNIT_FAMILIES|SUFFIXED|VERSION_RE|CHECK_SOURCES|BACKREFS.*)$")

# Words that mark a table's CONTENTS as a lab decision.
LAB_SIGNAL = re.compile(
    r"(recovery|rsd|rpd|tol|limit|min|max|ppt|ppb|ng/|level|expiry|shelf|"
    r"days|criteri|threshold|window|freq|r2|cas|code)", re.I)


def _table_name(line):
    match = re.match(r"^\s*(_?[A-Z][A-Z0-9_]{3,})\s*=", line)
    return match.group(1) if match else ""


def _looks_like_lab_table(name, body):
    if STRUCTURAL_TABLES.match(name):
        return False
    return bool(LAB_SIGNAL.search(body)) or bool(LAB_NUMBER.search(body))

SKIP_FILES = {"seed_calibrations.py", "audit_configurable.py",
              "derive_qc_coherent_fixture.py", "relabel_run_from_worklist.py"}


def walk(dirs, exts=(".py",)):
    """Templates and JS read configuration too.

    A Python-only scan overstates DEAD: a key consumed by a TAL template or by
    the drag-and-drop surrogate-map editor has no Python reader and would be
    reported as write-only.
    """
    for d in dirs:
        base = os.path.join(ROOT, d)
        for dirpath, _dirnames, filenames in os.walk(base):
            if "__pycache__" in dirpath or "/tests" in dirpath:
                continue
            for name in sorted(filenames):
                if not name.endswith(exts) or name in SKIP_FILES:
                    continue
                yield os.path.join(dirpath, name)


READ_EXTS = (".py", ".pt", ".js")


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _blank_docstrings(text):
    """Blank docstring bodies, keeping line numbers and doctest lines.

    Prose that quotes code reads as code: a docstring saying `this read
    profile["recovery_tiers"]` was reported as a live read of a retired key.
    String literals in general CANNOT be blanked -- the keys being searched for
    live inside them (`.get("unit_map")`) -- but a docstring is a string
    standing alone as a statement, which the parser can identify exactly.

    Doctest lines are preserved: `>>> profile["unit_map"]` is a real read, and
    a scanner that skipped whole docstrings would miss it.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        end = getattr(first, "end_lineno", first.lineno)
        for n in range(first.lineno - 1, min(end, len(lines))):
            if ">>>" not in lines[n]:
                lines[n] = ""
    return "\n".join(lines)


def rel(path):
    return os.path.relpath(path, ROOT)


def _scan(dirs, patterns, exts=(".py",)):
    hits = []
    for path in walk(dirs, exts):
        text = read(path)
        if path.endswith(".py"):
            text = _blank_docstrings(text)
        for n, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(p.search(line) for p in patterns):
                hits.append((rel(path), n, stripped))
    return hits


def find_reads(key):
    """Anywhere the key is READ — the worker, the add-on, or a view.

    Classifying by access pattern rather than by directory matters: a setting
    consumed by the add-on rather than the pipeline worker is still consumed.
    Splitting on location reported run_template and master_analyte_set as dead
    when both are read, just not by the worker.
    """
    return _scan(ALL_DIRS, [
        re.compile(r'\.get\(\s*["\']{0}["\']'.format(re.escape(key))),
        re.compile(r'\[\s*["\']{0}["\']\s*\](?!\s*=)'.format(re.escape(key))),
    ], exts=READ_EXTS)


def find_writes(key):
    """Anywhere the key is WRITTEN — assignment or setdefault."""
    return _scan(ALL_DIRS, [
        re.compile(r'setdefault\(\s*["\']{0}["\']'.format(re.escape(key))),
        re.compile(r'\[\s*["\']{0}["\']\s*\]\s*='.format(re.escape(key))),
        re.compile(r'["\']{0}["\']\s*:'.format(re.escape(key))),
    ])


MAX_DEPTH = 3

# Containers whose keys are DATA, not settings — analyte names, matrix names,
# lot codes. Descending into them enumerates the lab's content as if it were
# schema and buries the real findings.
DATA_KEYED = {
    "spike_levels", "salt_factors", "matrix_factors", "cas_map", "unit_map",
    "matrix_aliases", "matrix_uid_map", "eis_matrix_overrides",
    "spec_overrides", "surrogate_map", "surrogate_is_chain", "isomer_sums",
    "analyte_matrix_inclusion",
}

# Names alone can't keep up with a growing lab, so judge the CONTENTS too: a
# dict keyed by analyte or matrix names is the lab's data, and enumerating it
# as schema buries the findings. Naming only the containers I happened to know
# produced 679 "keys" and 404 false DEAD entries, nearly all of them one
# analyte x matrix cell.
def _is_data_keyed(name, node):
    if name in DATA_KEYED:
        return True
    if not isinstance(node, dict) or len(node) < 4:
        return False
    if len(node) > 12:
        return True
    lab_like = sum(1 for k in node
                   if re.search(r"[ :/]|^\d", str(k)))
    return lab_like * 2 > len(node)


def profile_keys(profiles_path):
    """Every settable path in the method profiles, to MAX_DEPTH.

    Descending only into instrument_verification examined 36 keys and never
    reached qc_acceptance — the container migrate_profile_structure rehomed the
    retired flat keys into, and therefore the one place a flat-vs-nested split
    is most likely to survive. A shallow walk reports SPLIT KEY (0) by
    construction, which reads as "clean" when it means "did not look".
    """
    keys = {}
    data = {}
    if profiles_path and os.path.exists(profiles_path):
        with open(profiles_path, encoding="utf-8") as fh:
            data = json.load(fh)

    def descend(node, prefix, method, depth):
        if depth > MAX_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                path = "{0}.{1}".format(prefix, key) if prefix else key
                keys.setdefault(path, set()).add(method)
                if _is_data_keyed(key, value):
                    continue
                descend(value, path, method, depth + 1)
        elif isinstance(node, list):
            # A list of settings objects (recovery tiers, calibration levels):
            # the members share a shape, so collapse the index.
            for item in node:
                if isinstance(item, dict):
                    descend(item, "{0}[]".format(prefix), method, depth)

    for method, profile in (data or {}).items():
        if isinstance(profile, dict):
            descend(profile, "", method, 1)
    return keys


def _ancestors(key):
    """Container paths above a key, nearest first."""
    parts = key.replace("[]", "").split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def _subscriber_modules():
    """Modules registered as ZCML event handlers.

    A write from one of these is UI-driven even though it is not under
    browser/: spec_reverse.on_spec_modified fires when a manager edits a core
    SENAITE AnalysisSpec and writes the result into the method profile. Judging
    editability by directory alone reported spec_overrides as unreachable when
    it has a perfectly good editor -- core's, rather than one of ours.
    """
    mods = set()
    for dirpath, _d, filenames in os.walk(os.path.join(ROOT, "src")):
        for name in filenames:
            if not name.endswith(".zcml"):
                continue
            text = read(os.path.join(dirpath, name))
            for match in re.finditer(r'handler="\.?([\w.]+)\.\w+"', text):
                mods.add(match.group(1).split(".")[-1])
    return mods


SUBSCRIBER_MODULES = None


def _is_ui_writer(path):
    """Does a write at this path originate from a user action?"""
    global SUBSCRIBER_MODULES
    if SUBSCRIBER_MODULES is None:
        SUBSCRIBER_MODULES = _subscriber_modules()
    if "method_profile_store" in path:
        return False          # a seed table, not the lab configuring anything
    if "browser/" in path:
        return True
    return _stem(path).split("/")[-1] in SUBSCRIBER_MODULES


def _stem(path):
    """Identify the FEATURE a file belongs to.

    browser/run_builder.py and browser/templates/run_builder.pt are one
    feature. Keying on the bare basename instead collided
    pfas_pipeline/method_profiles.py with browser/method_profiles.py and
    discounted the pipeline — the actual consumer — as the editor reading
    itself back.
    """
    path = path.replace("browser/templates/", "browser/")
    return os.path.splitext(path)[0]


def _consumers(reads, writers):
    """Reads by something OTHER than the editor that writes the setting.

    "Under browser/" is the wrong test: run_builder and extraction_guide read
    their settings from browser/ and are genuinely the consumers — the feature
    lives there. What marks a setting as inert is narrower: the only code that
    ever reads it is the same file that writes it, plus that file's own
    template. Salt adjustment is the case in point.
    """
    owned = {_stem(w) for w in writers}
    return [r for r in reads
            if _stem(r[0]) not in owned and "/migrations/" not in r[0]
            and not r[0].endswith(("method_profile_store.py", "egad_store.py"))]


# Calls that YIELD a method profile dict. A name assigned from one of these is
# a profile for the rest of its scope.
PROFILE_SOURCE_CALLS = {
    "get_profile", "_profile_data", "_method_profile", "profile",
    "_get_profile", "get_method_profile",
}
# Bases whose `.get(...)` yields a METHOD profile. Named explicitly rather than
# matched on "profile" appearing in the name: this codebase calls three
# different things a profile — the METHOD profile, the Import Studio instrument
# profile (`import_studio.py`), and the EGAD state profile (`egad_config.py`) —
# and a name-based heuristic reported the latter two's keys (vendor, retired,
# map, state, columns, aliases) as missing method-profile producers. Same word,
# different concept; only the first one belongs here.
PROFILE_CACHE_BASES = {"_profile_data_cache", "_DEFAULT_PROFILE_CACHE"}

# NOTE: there is deliberately NO name-based rule (a parameter called `profile`
# is not evidence). Tracking is by ASSIGNMENT from a known method-profile
# source only, which is what distinguishes the three vocabularies above.

# Keys read off a profile that are legitimately absent from the data: either a
# deliberate NOT WIRED obligation, or a name the code probes defensively.
# Anything NOT listed here that the code reads and no profile supplies is a
# consumer with no producer and fails the audit.
NO_PRODUCER_ALLOWED = {
    # Add entries as "key": "why it is allowed to have no producer".
}


def code_read_profile_keys():
    """Keys the CODE reads off a method profile, whatever the data contains.

    WHY THIS EXISTS. `profile_keys()` enumerates the profile JSON, and
    `audit_keys()` only ever examined those — so the key universe was whatever
    happened to be in the data. A key the code READS that has never been written
    into any profile was invisible, and "0 UNREACHABLE" therefore meant "no key
    in the data goes unread", not "no key the code reads goes unwritten".

    `internal_standards` is exactly that case: read by
    `pfas_pipeline/method_profiles.py:get_is_list`, present in no profile, so
    `get_is_list` returns [] for both EPA methods and NO surrogate or internal
    standard check runs on either (GAPS.md §19). It survived four months of a
    clean audit because the audit's own input was the convenient case.

    WHY AST AND NOT A REGEX. The first version of this matched profile-shaped
    receiver names on a single line. It reported 19 keys and MISSED
    `internal_standards` — the one case it was built for — because the real read
    is `data.get("internal_standards")` where `data` was bound from
    `_profile_data_cache.get(method_id, {})` two lines earlier. A line-based
    pattern cannot know what a local variable holds, so it collected unrelated
    dicts (`error`, `map`, `columns`, `vendor`) and none of the profile ones.
    19 false positives and 0 true positives is worse than no check: it teaches
    the reader to skip the section.

    Returns {key: [(file, line, source), ...]}.
    """
    found = defaultdict(list)

    # Wrapper functions that RETURN a profile are profile sources too. Derived
    # rather than listed: narrowing the source set by hand lost
    # `extraction_logbook` (read off `run_builder._profile(method_id)`, which is
    # `return get_profile(...)`) — a real finding, silently, because the wrapper
    # was not in the hardcoded set. Discovering them means a wrapper added later
    # is covered without anyone remembering to update a list.
    # PER FILE, never global. A shared name-keyed set leaked across modules:
    # qc_grid._load_profile returns a METHOD profile, import_studio._load_profile
    # returns an INSTRUMENT profile, and classifying the name globally made the
    # second inherit the first's meaning — reporting `map` and `vendor_key` as
    # missing method-profile producers. Third instance of one root cause in this
    # function (module-scope leak, then function-scope leak, now cross-module):
    # a name is only ever meaningful inside the scope that defines it.
    wrappers_by_path = {}
    active = set()

    def _returns_profile(fn_node, known):
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Return) and node.value is not None:
                val = node.value
                # `return get_profile(...) or {}`
                if isinstance(val, ast.BoolOp) and val.values:
                    val = val.values[0]
                if isinstance(val, ast.Call):
                    name = (getattr(val.func, "id", None)
                            or getattr(val.func, "attr", None))
                    if name in PROFILE_SOURCE_CALLS or name in known:
                        return True
        return False

    for path in walk(ALL_DIRS, (".py",)):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        known = set()
        # Two passes so a wrapper of a wrapper in the SAME file is caught. A
        # wrapper imported from another module is deliberately not followed:
        # missing one is the safer direction than inheriting a foreign meaning.
        for _ in range(2):
            for node in ast.walk(tree):
                if (isinstance(node, ast.FunctionDef)
                        and _returns_profile(node, known)):
                    known.add(node.name)
        wrappers_by_path[rel(path)] = known

    def profile_yielding(node):
        """Does this expression evaluate to a method profile?"""
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in PROFILE_SOURCE_CALLS or name in active:
                return True
            # _profile_data_cache.get(method_id, {}) -- the worker's own cache
            if name == "get" and isinstance(fn, ast.Attribute):
                if getattr(fn.value, "id", None) in PROFILE_CACHE_BASES:
                    return True
        return False

    def own_nodes(scope):
        """Every node in `scope`, stopping at nested function/class boundaries.

        `ast.walk` descends through them, which leaked names ACROSS functions: a
        module-level walk of method_profiles.py picked up `p = get_profile(...)`
        at line 80 and then attributed every `p.get("...")` in the file to it —
        including an unrelated `for p in rule.get("params")` loop variable 400
        lines later, reporting `default`/`label`/`type` as missing profile keys.
        A name means a profile only inside the scope that bound it.
        """
        stack = list(getattr(scope, "body", []))
        while stack:
            node = stack.pop()
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    continue
                stack.append(child)

    def tracked_names(scope):
        """Names bound to a METHOD profile by assignment in THIS scope only.

        Assignment only. A parameter or local merely CALLED `profile` is not
        evidence — see PROFILE_CACHE_BASES on the three different things this
        codebase calls a profile.
        """
        names = set()
        for node in own_nodes(scope):
            if isinstance(node, ast.Assign) and profile_yielding(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    seen = set()

    def record(path, lines, key, node):
        # Module and FunctionDef scopes overlap under ast.walk, so a read inside
        # a function is visited from both and was reported twice. Dedupe on the
        # site itself rather than trying to partition the scopes.
        line_no = getattr(node, "lineno", 0)
        fingerprint = (rel(path), line_no, key)
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        src = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
        found[key].append((rel(path), line_no, src))

    for path in walk(ALL_DIRS, (".py",)):
        text = read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        # This file's own wrappers only — see wrappers_by_path above.
        active = wrappers_by_path.get(rel(path), set())
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.Module))]
        for scope in scopes:
            names = tracked_names(scope)
            if not names:
                continue
            for node in own_nodes(scope):
                # <tracked>.get("KEY")
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and getattr(node.func.value, "id", None) in names
                        and node.args):
                    arg = node.args[0]
                    if isinstance(arg, ast.Str):
                        record(path, lines, arg.s, node)
                    elif isinstance(arg, ast.Constant) and isinstance(
                            arg.value, str):
                        record(path, lines, arg.value, node)
                # <tracked>["KEY"]
                elif (isinstance(node, ast.Subscript)
                        and getattr(node.value, "id", None) in names):
                    idx = node.slice
                    idx = getattr(idx, "value", idx)
                    if isinstance(idx, ast.Str):
                        record(path, lines, idx.s, node)
                    elif isinstance(idx, ast.Constant) and isinstance(
                            idx.value, str):
                        record(path, lines, idx.value, node)
    return found


def audit_no_producer(profiles_path):
    """Keys the code reads off a profile that NO profile supplies.

    The second of §13's two defect shapes — a consumer with no producer —
    applied to the profile store. Distinct from UNREACHABLE, which is "the
    engine reads it and no UI writes it": here nothing writes it at all, so the
    read silently yields None/[] forever.
    """
    present = {k.split(".")[-1] for k in profile_keys(profiles_path)}
    findings = []
    for key, sites in sorted(code_read_profile_keys().items()):
        if key in present or key in CONTAINER_KEYS or key in DERIVED_KEYS:
            continue
        if key in NO_PRODUCER_ALLOWED:
            continue
        # A migration's whole job is reading keys that no longer exist, so a
        # legacy key read ONLY there is correct rather than a gap. Same filter
        # the read-side checks already apply (see _external_reads).
        sites = [s for s in sites if "/migrations/" not in s[0]]
        if not sites:
            continue
        findings.append((key, sites))
    return findings


def audit_keys(profiles_path):
    dead, unreachable, split, derived, uionly, legacy = [], [], [], [], [], []
    keys = profile_keys(profiles_path)
    if not keys:
        return dead, unreachable, split, 0

    nested_names = {}
    for k in keys:
        if "." in k:
            nested_names.setdefault(k.rsplit(".", 1)[1].lower(), []).append(k)

    for key in sorted(keys):
        leaf = key.split(".")[-1]
        if leaf in CONTAINER_KEYS:
            continue
        if leaf in DERIVED_KEYS:
            derived.append((key, DERIVED_KEYS[leaf]))
            continue
        reads = find_reads(leaf)
        writes = find_writes(leaf)
        # A write inside a default/seed table is not the lab configuring it.
        editable = [w for w in writes if _is_ui_writer(w[0])]
        # An editor that writes the whole container back — `for key in qca:
        # qca[key]["enabled"] = ...; profile["qc_acceptance"] = qca` — makes
        # every leaf under it reachable without naming any of them. Matching
        # leaf names alone would call those settings unreachable.
        if not editable:
            for ancestor in _ancestors(key):
                if any("browser/" in w[0] for w in find_writes(ancestor)):
                    editable = [("via the {0} editor".format(ancestor), 0, "")]
                    break
        if writes and not reads:
            # The mirror of the container-writer case: an engine that iterates
            # `for key in qc_acceptance` reads every leaf under it without
            # naming one, so a literal-name scan sees no reader and calls a
            # live setting dead.
            if not any(find_reads(a) for a in _ancestors(key)):
                dead.append((key, writes[:3]))
        elif reads and editable and not _consumers(
                reads, [w[0] for w in editable]):
            # Written by an editor and read back only BY that editor. It looks
            # completely alive — a form, a saved value, the value redisplayed —
            # and nothing downstream ever consumes it. Salt adjustment sat here:
            # two UIs, three storage keys, applied by nothing.
            inherited = [r for a in _ancestors(key) for r in find_reads(a)]
            if not _consumers(inherited, [w[0] for w in editable]):
                uionly.append((key, reads[:3]))
        elif reads and not editable:
            # A key read ONLY by a migration is legacy, not unreachable: the
            # migration exists to carry its value into the current structure
            # and then drop it. Reporting it as a configurability gap invites
            # someone to build a UI for a key that is on its way out.
            live = [r for r in reads if "/migrations/" not in r[0]]
            if live:
                unreachable.append((key, live[:3]))
            else:
                legacy.append((key, reads[:3]))
        if "." not in key and key.lower() in nested_names:
            split.append((key, ", ".join(sorted(nested_names[key.lower()]))))
    return dead, unreachable, split, derived, uionly, legacy, len(keys)


def audit_hardcoded():
    out = []
    for path in walk(ENGINE_DIRS + STORE_DIRS):
        text = read(path)
        if "_DEFAULT_PROFILE_CACHE" in text and path.endswith("method_profiles.py"):
            pass  # the documented fallback cache; reported separately below
        for n, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            for pattern, why in HARDCODED_HINTS:
                if not pattern.search(line):
                    continue
                if why == "module-level table":
                    name = _table_name(line)
                    body = "\n".join(
                        text.splitlines()[n - 1:n + 14])
                    if not _looks_like_lab_table(name, body):
                        break
                    why = "lab table in code"
                out.append((rel(path), n, why, stripped[:110]))
                break
    return out


def emit_text(dead, unreachable, split, derived, uionly, legacy, hardcoded, total):
    print("Configurability audit — CLAUDE.md §1.1")
    print("=" * 72)
    print("profile keys examined: {0}\n".format(total))

    def block(title, why, rows, render):
        print("{0}  ({1})".format(title, len(rows)))
        print("-" * 72)
        print("  {0}\n".format(why))
        if not rows:
            print("  none\n")
            return
        for row in rows:
            render(row)
        print()

    block("DEAD CONFIG",
          "the UI writes it; no engine code reads it. Editing changes nothing.",
          dead,
          lambda r: (print("  {0}".format(r[0])),
                     [print("      written at {0}:{1}".format(h[0], h[1]))
                      for h in r[1]]))
    block("UNREACHABLE CONFIG",
          "the engine reads it; no UI writes it. The lab cannot change it.",
          unreachable,
          lambda r: (print("  {0}".format(r[0])),
                     [print("      read at    {0}:{1}".format(h[0], h[1]))
                      for h in r[1]]))
    block("UI-ONLY CONFIG",
          "an editor writes it and reads it back; nothing downstream consumes "
          "it. Looks alive, changes nothing. (A self-contained feature that "
          "stores AND consumes its own config -- the Run Builder template -- "
          "lands here legitimately; judge each one.)",
          uionly,
          lambda r: (print("  {0}".format(r[0])),
                     [print("      read back at {0}:{1}".format(h[0], h[1]))
                      for h in r[1]]))
    block("LEGACY — migration-only (not a finding)",
          "read only by a migration, which carries the value forward and drops "
          "the key. Do not build a UI for these.",
          legacy,
          lambda r: (print("  {0}".format(r[0])),
                     [print("      carried at {0}:{1}".format(h[0], h[1]))
                      for h in r[1]]))
    block("DERIVED (not a finding)",
          "read but never hand-edited by design — the system computes them.",
          derived,
          lambda r: print("  {0}\n      derived by {1}".format(r[0], r[1])))
    block("SPLIT KEY",
          "the same setting exists at two paths — the residue that four "
          "separate defects came out of.",
          split,
          lambda r: print("  {0}   vs   {1}".format(r[0], r[1])))
    block("HARDCODED LAB VALUES",
          "literals a lab would want to change, living in code.",
          hardcoded,
          lambda r: print("  {0}:{1}  [{2}]\n      {3}".format(*r)))


def emit_md(dead, unreachable, split, derived, uionly, legacy, hardcoded, total):
    print("# Configurability audit\n")
    print("`tools/audit_configurable.py` · {0} profile keys examined\n".format(total))
    for title, why, rows in (
        ("Dead config", "The UI writes it; no engine code reads it. "
         "Editing it changes nothing.", dead),
        ("Unreachable config", "The engine reads it; no UI writes it. "
         "The lab cannot change it.", unreachable),
        ("UI-only config", "An editor writes it and reads it back; nothing "
         "downstream consumes it. Looks alive, changes nothing.", uionly),
    ):
        print("## {0} ({1})\n\n{2}\n".format(title, len(rows), why))
        if not rows:
            print("None.\n")
            continue
        print("| key | evidence |")
        print("|---|---|")
        for key, hits in rows:
            print("| `{0}` | {1} |".format(
                key, "<br>".join("`{0}:{1}`".format(h[0], h[1]) for h in hits)))
        print()
    print("## Derived — not findings ({0})\n".format(len(derived)))
    if derived:
        print("| key | derived by |\n|---|---|")
        for key, how in derived:
            print("| `{0}` | {1} |".format(key, how))
    print()
    print("## Split keys ({0})\n".format(len(split)))
    if split:
        print("| flat | nested |\n|---|---|")
        for a, b in split:
            print("| `{0}` | `{1}` |".format(a, b))
    else:
        print("None.")
    print("\n## Hardcoded lab values ({0})\n".format(len(hardcoded)))
    print("| location | kind | line |\n|---|---|---|")
    for path, line, why, text in hardcoded:
        print("| `{0}:{1}` | {2} | `{3}` |".format(path, line, why,
                                                   text.replace("|", "\\|")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles",
                    default=os.path.join(ROOT, "data", "qc",
                                         "method_profiles.json"),
                    help="exported method profile JSON to enumerate keys from")
    ap.add_argument("--format", choices=("text", "md"), default="text")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when a key the code reads has no "
                         "producer and is not in NO_PRODUCER_ALLOWED")
    args = ap.parse_args()

    (dead, unreachable, split, derived, uionly, legacy,
     total) = audit_keys(args.profiles)
    hardcoded = audit_hardcoded()
    no_producer = audit_no_producer(args.profiles)
    if not total:
        print("No method profile JSON at {0} — key audit skipped; run with "
              "--profiles pointing at the exported file.".format(args.profiles),
              file=sys.stderr)
    (emit_md if args.format == "md" else emit_text)(
        dead, unreachable, split, derived, uionly, legacy, hardcoded, total)

    # NO PRODUCER is reported separately and can FAIL the run. The other checks
    # report only: they have been clean for months and a regression there is a
    # different conversation. This one exists because a silent consumer with no
    # producer survived four months of a clean audit (GAPS.md §19), so the
    # default is to be loud, and a deliberate case goes in NO_PRODUCER_ALLOWED
    # with its reason rather than being tolerated by silence.
    print("")
    print("NO PRODUCER ({0}) — read off a profile, written by nothing".format(
        len(no_producer)))
    if not no_producer:
        print("  none")
    for key, sites in no_producer:
        print("  {0}".format(key))
        for path, line, src in sites[:4]:
            print("      read at {0}:{1}".format(path, line))
        if len(sites) > 4:
            print("      ... and {0} more".format(len(sites) - 4))
    if args.strict and no_producer:
        print("")
        print("FAIL: {0} key(s) read with no producer. Either give them one, "
              "or add each to NO_PRODUCER_ALLOWED with a reason.".format(
                  len(no_producer)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
