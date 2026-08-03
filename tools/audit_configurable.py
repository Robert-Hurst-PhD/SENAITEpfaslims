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


def rel(path):
    return os.path.relpath(path, ROOT)


def _scan(dirs, patterns, exts=(".py",)):
    hits = []
    for path in walk(dirs, exts):
        for n, line in enumerate(read(path).splitlines(), 1):
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


def audit_keys(profiles_path):
    dead, unreachable, split, derived = [], [], [], []
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
        editable = [w for w in writes
                    if "browser/" in w[0] and "method_profile_store" not in w[0]]
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
        elif reads and not editable:
            unreachable.append((key, reads[:3]))
        if "." not in key and key.lower() in nested_names:
            split.append((key, ", ".join(sorted(nested_names[key.lower()]))))
    return dead, unreachable, split, derived, len(keys)


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


def emit_text(dead, unreachable, split, derived, hardcoded, total):
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


def emit_md(dead, unreachable, split, derived, hardcoded, total):
    print("# Configurability audit\n")
    print("`tools/audit_configurable.py` · {0} profile keys examined\n".format(total))
    for title, why, rows in (
        ("Dead config", "The UI writes it; no engine code reads it. "
         "Editing it changes nothing.", dead),
        ("Unreachable config", "The engine reads it; no UI writes it. "
         "The lab cannot change it.", unreachable),
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
    args = ap.parse_args()

    dead, unreachable, split, derived, total = audit_keys(args.profiles)
    hardcoded = audit_hardcoded()
    if not total:
        print("No method profile JSON at {0} — key audit skipped; run with "
              "--profiles pointing at the exported file.".format(args.profiles),
              file=sys.stderr)
    (emit_md if args.format == "md" else emit_text)(
        dead, unreachable, split, derived, hardcoded, total)


if __name__ == "__main__":
    main()
