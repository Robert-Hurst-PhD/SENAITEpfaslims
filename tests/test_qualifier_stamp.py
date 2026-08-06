"""The qualifier stamp must survive the trip from approval to the certificate.

A qualified release is only defensible if the certificate SAYS the result was
qualified (ISO 17025 §7.8.4). The code is written onto each affected analysis at
approve time and read back at render time — two ends, in two modules, six months
apart in a future maintainer's reading order.

They were already out of step once. `_stamp_qualifier_remarks` formatted the
marker inline and justified it with "Remarks is the one per-analysis field core
already prints". Core prints no such thing: `senaite/impress/analysisrequest/
templates/results.pt` has no remarks cell, and `remarks.pt` renders SAMPLE-level
`model.getRemarks()`, a different field. Verified against a real published
certificate — 14 stamped analyses on FEED-0002, `QC: M` absent from the rendered
HTML with `show_remarks` both off AND on. The stamps went into a void.

So the format now lives once, in `qc_qualification`, with its writer and reader
beside each other. These tests pin that contract. They deliberately do NOT
import Plone: `qc_qualification` is Python-2.7 add-on code, but these two
functions are pure string handling and must stay that way — the moment they need
a portal, the certificate's marker depends on request state.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "senaite", "pfas", "qc_qualification.py")


def _load_string_helpers():
    """Exec just the marker helpers, without importing the Plone module.

    `qc_qualification` imports `bika.lims` at module scope, which does not exist
    outside the container. The helpers under test are self-contained, so the
    block that defines them is extracted and executed on its own — which also
    asserts, by construction, that they stay free of Plone dependencies.
    """
    import ast
    with open(SRC) as fh:
        src = fh.read()
    tree = ast.parse(src, SRC)
    wanted = ("REMARK_PREFIX", "format_remark_codes", "parse_remark_codes")
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in wanted for t in node.targets):
            keep.append(node)
    tree.body = keep
    ns = {}
    exec(compile(tree, SRC, "exec"), ns)
    assert "format_remark_codes" in ns and "parse_remark_codes" in ns, sorted(ns)
    return ns


NS = _load_string_helpers()
format_remark_codes = NS["format_remark_codes"]
parse_remark_codes = NS["parse_remark_codes"]
REMARK_PREFIX = NS["REMARK_PREFIX"]


def test_a_stamp_reads_back_as_what_was_written():
    for codes in (["M"], ["M", "P"], ["NC"], ["J", "B", "M"]):
        marker = format_remark_codes(codes)
        assert parse_remark_codes(marker) == sorted(codes), (codes, marker)


def test_the_stamp_survives_remarks_that_were_already_there():
    """Analyses carry other remarks — `SUR`, `N.C.`, `br-PFOS:(QQ)` were all
    present on FEED-0002. The stamp is appended on its own line."""
    existing = u"SUR\nbr-PFOS:(QQ)"
    marker = format_remark_codes(["M"])
    combined = existing + u"\n" + marker
    assert parse_remark_codes(combined) == ["M"], combined


def test_unrelated_remarks_never_become_a_qualifier():
    """The failure that matters most: a stray remark must not print a code on a
    certificate. Only a line starting with the prefix is read."""
    for noise in (u"", u"SUR", u"N.C.", u"br-PFHxS:(N.C.)",
                  u"see QC: M in the batch file",   # prefix present, not leading
                  u"quality check: M", u"QC M"):
        assert parse_remark_codes(noise) == [], noise


def test_empty_input_writes_nothing():
    """A stamp of no codes must produce no remark at all — an empty `QC: ` line
    would parse back as nothing but still sit on the analysis as noise."""
    for empty in (None, [], [u""], [u"  "], [None]):
        assert format_remark_codes(empty) == u"", empty


def test_the_writer_is_the_only_producer_of_the_stamp():
    """If another module starts formatting the marker inline, the two ends can
    drift again — which is the defect this whole file exists to prevent."""
    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "src")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.basename(path) == "qc_qualification.py":
                continue
            with open(path) as fh:
                body = fh.read()
            if re.search(r'["\']QC: \{', body) or re.search(r'["\']QC: %s', body):
                offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, (
        "these format the qualifier marker inline instead of calling "
        "qc_qualification.format_remark_codes: %s" % offenders)


def test_the_reader_is_wired_into_the_report_view():
    """The stamp is worthless unless something renders it. This asserts the
    consumer exists — the original defect was a producer with no consumer."""
    view = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "reportview.py")
    assert os.path.exists(view), "browser/reportview.py is gone"
    with open(view) as fh:
        body = fh.read()
    assert "parse_remark_codes" in body, "report view no longer reads the stamp"
    assert "get_formatted_result" in body, (
        "report view no longer overrides the value formatter — core's "
        "results.pt renders the value through model.get_formatted_result")
    zcml = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "configure.zcml")
    with open(zcml) as fh:
        reg = fh.read()
    assert "PFASSingleReportView" in reg, (
        "the report view is not registered — impress would fall back to core's "
        "and the markers would silently disappear")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
