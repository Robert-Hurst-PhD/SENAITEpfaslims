# -*- coding: utf-8 -*-
"""Regression tests for senaite.pfas.logbook_schema.

The module under test is deliberately free of Zope imports, so it is loaded
straight from its path — importing the senaite.pfas package would drag in
zope.i18nmessageid. Runs under both Python 2.7 (the add-on runtime) and
Python 3 (developer machines).

    python tests/test_logbook_schema.py
"""
from __future__ import print_function
import os
import sys

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "src", "senaite", "pfas", "logbook_schema.py")

try:                                    # Python 3.4+
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("ls", _PATH)
    ls = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(ls)
except ImportError:                     # Python 2.7
    import imp
    ls = imp.load_source("ls", _PATH)

ok = fail = 0
def chk(desc, cond):
    global ok, fail
    if cond: ok += 1; print("  PASS", desc)
    else:    fail += 1; print("  FAIL", desc)

print("== validate_schema ==")
chk("valid schema has no errors",
    ls.validate_schema([{"name":"a","label":"A","type":"text"}]) == [])
chk("leading underscore rejected",
    any("underscore" in e for e in ls.validate_schema([{"name":"_x","type":"text"}])))
chk("_json suffix rejected",
    any("_json" in e for e in ls.validate_schema([{"name":"foo_json","type":"text"}])))
chk("duplicate name rejected",
    any("duplicate" in e for e in ls.validate_schema(
        [{"name":"a","type":"text"},{"name":"a","type":"text"}])))
chk("unknown type rejected",
    any("unknown type" in e for e in ls.validate_schema([{"name":"a","type":"nope"}])))
chk("table needs a column",
    any("at least one column" in e for e in ls.validate_schema(
        [{"name":"t","type":"table","columns":[]}])))
chk("bad column type rejected",
    any("column type" in e for e in ls.validate_schema(
        [{"name":"t","type":"table","columns":[{"name":"c","type":"lot_ref"}]}])))
chk("uppercase name rejected",
    ls.validate_schema([{"name":"Bad","type":"text"}]) != [])

print("== canonicalize_schema ==")
c = ls.canonicalize_schema([{"name":"n","type":"textarea","width":"lg","required":True,
                            "correctable":True}])[0]
chk("width/required stripped from textarea", "width" not in c and "required" not in c)
chk("correctable kept on textarea", c.get("correctable") is True)
c2 = ls.canonicalize_schema([{"name":"t","type":"table",
                              "columns":[{"name":"c","type":"lot_ref"}]}])[0]
chk("table column type coerced to text", c2["columns"][0]["type"] == "text")
c3 = ls.canonicalize_schema([{"name":"cb","type":"checkbox","correctable":True}])[0]
chk("correctable stripped from checkbox", "correctable" not in c3)

print("== build_steps ==")
fields = [{"name":"a","type":"text"},{"name":"b","type":"text"},{"name":"c","type":"text"}]
steps  = [{"id":"s1","title":"One","fields":["a"]}]
b = ls.build_steps(fields, steps)
chk("unassigned swept into trailing step", len(b) == 2 and b[1]["id"] == "_unassigned")
chk("unassigned holds b and c",
    [f["name"] for f in b[1]["fields"]] == ["b","c"])
b2 = ls.build_steps(fields, [{"id":"s1","title":"1","fields":["a"]},
                             {"id":"s2","title":"2","fields":["a","b"]}])
chk("double-claimed field goes to first step only",
    [f["name"] for f in b2[0]["fields"]] == ["a"] and
    [f["name"] for f in b2[1]["fields"]] == ["b"])
b3 = ls.build_steps(fields, [{"id":"s1","title":"1","fields":["a","GONE"]}])
chk("stale field name dropped silently",
    [f["name"] for f in b3[0]["fields"]] == ["a"])
b4 = ls.build_steps(fields, [{"id":"s1","title":"1","fields":["a","b","c"]}])
chk("no trailing step when all assigned", len(b4) == 1)
chk("no fields -> no steps at all", ls.build_steps([], []) == [])

print("== validate_steps ==")
chk("duplicate claim across steps rejected",
    any("already used" in e for e in ls.validate_steps(
        [{"id":"s1","title":"A","fields":["x"]},
         {"id":"s2","title":"B","fields":["x"]}], fields)))
chk("stale name is NOT an error",
    ls.validate_steps([{"id":"s1","title":"A","fields":["GONE"]}], fields) == [])
chk("missing title rejected",
    any("title" in e for e in ls.validate_steps([{"id":"s1","title":""}], fields)))
chk("duplicate step id rejected",
    any("duplicate id" in e for e in ls.validate_steps(
        [{"id":"s1","title":"A"},{"id":"s1","title":"B"}], fields)))
chk("empty steps ok", ls.validate_steps([], fields) == [])

print("== unassigned_names ==")
chk("reports b,c", ls.unassigned_names(fields, steps) == ["b","c"])

print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
