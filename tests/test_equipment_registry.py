# -*- coding: utf-8 -*-
"""The equipment registry (browser/equipment.py, GAPS §100b) must find
instruments for an ANONYMOUS caller: the sensor ingest endpoint is public and
authenticates with its API key. A permission-filtered catalog search returns
nothing to it (checked live: 0 instruments), so every provider lookup is
unrestricted, as the SQLite registry it replaced was."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EQUIPMENT = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "equipment.py")
PROVIDER = ("available", "list_units", "get_unit", "get_unit_by_sensor", "unit_by_serial",
            "_instruments", "_by_uid", "_instrument_type", "unit_for", "type_requirements")


def _funcs():
    with open(EQUIPMENT) as fh:
        tree = ast.parse(fh.read())
    return dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))


def test_provider_lookups_are_unrestricted():
    funcs = _funcs()
    for name in PROVIDER:
        assert name in funcs, name
        src = ast.dump(funcs[name])
        for restricted in ("attr='search'", "attr='get_object_by_uid'", "attr='getInstrumentType'"):
            assert restricted not in src, "%s uses a permission-filtered lookup (%s)" % (name, restricted)
    for name in ("_instruments", "_by_uid"):
        assert "unrestrictedSearchResults" in ast.dump(funcs[name]), name
        assert "_unrestrictedGetObject" in ast.dump(funcs[name]), name


def test_the_ingest_endpoint_is_still_public():
    zcml = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "configure.zcml")
    with open(zcml) as fh:
        body = fh.read()
    block = body[body.index('name="pfas-sensor-ingest"'):][:300]
    assert 'permission="zope2.Public"' in block, "if this changes, the anonymous premise above does too"
