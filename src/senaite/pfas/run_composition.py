# -*- coding: utf-8 -*-
"""
Pure QC-COMPOSITION transforms for the LC-MS run builder
(senaite.pfas.browser.run_builder).

A QAPP can override two different things about a method's QC (the lab's own
words): "all samples run in duplicate" and "LFSMs get run in more regular
intervals" -- i.e. WHICH injections a run contains and HOW OFTEN, not the
numeric acceptance criteria those injections are judged against. The numeric
criteria (recovery windows, RPD ceilings, r2 floors) already resolve through
the three-tier project -> lab -> baseline path in senaite.pfas.ruleset; this
module is the SAME override class's composition half, kept in its own
Zope-free module for the same reason ruleset.py / method_baselines.py /
holding_time.py are: it is loadable and unit-testable by path
(`importlib.util.spec_from_file_location`) without a running Plone instance,
which matters here because run_builder.py itself cannot be (it imports
zope.annotation / Products.CMFCore / Products.Five at module load).

Explicitly NOT here: "an additional surrogate is used." That changes analyte
relationships (the surrogate-to-IS map), which CLAUDE.md Sec3 makes a
method-owned single-source fact (analyte_reference.py / the method's own
surrogate map) -- duplicating it per-QAPP would re-create the defects
GAPS.md Sec13 catalogs. Out of scope by design, not an oversight.

SAFETY PROPERTY (both transforms are IDENTITY on their default arguments):
duplicate_all_samples=None/False and lfsm_frequency=None/0 together make
compose_sample_block() return exactly `[(row, "sample") for row in
sample_rows]` -- the untouched input, in order. That is the project-less
default every existing batch resolves to (senaite.pfas.ruleset's resolve()
rule 3: no project -> no lab data for these two keys yet -> None), which is
what lets a project-less batch build byte-for-byte the same sequence it
built before this module existed. tests/test_run_composition.py pins this.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals


def classify_sample_role(row):
    """The QC role a registered sample `row` plays, guessed from its id, or
    "" if it names no recognizable QC role (i.e. it is a genuine field
    sample). Moved here from run_builder.PFASRunBuilderView._role_from_sample
    so that method (redundant-QC suppression: a role already covered by a
    registered sample must not also get a sequence-token injection) and
    is_field_sample() below -- which needs the identical judgement to decide
    what duplicate_all_samples/lfsm_frequency may touch -- share ONE
    definition (CLAUDE.md Sec3) instead of drifting apart as two copies.

    A duplicate is written "LFSM Mid Duplicate" at least as often as
    "LFSMD" on real sample ids, so LFSMD is matched on either spelling.
    """
    raw = (row.get("client_sample_id") or row.get("sample_id") or u"")
    sid = raw.upper()
    if "LFSMD" in sid or ("LFSM" in sid and "DUP" in sid):
        return "LFSMD"
    if "LFSM" in sid:
        return "LFSM"
    if "MB" in sid.split():
        return "MB"
    for code in ("ICV", "CCV", "LFB", "CCB"):
        if code in sid:
            return code
    return u""


# The extraction log's `sample_type`/`role` column (run_builder.sample_rows()
# reads it into row["role"]) is the QC ROLE, but its value for an ORDINARY
# field sample is the literal string "Sample" -- not blank. Only these are
# actual QC types that disqualify a row from being a field sample; anything
# else explicit (including "Sample", or a role senaite.pfas has never heard
# of) falls through to the id-based guess (classify_sample_role) rather than
# being treated as disqualifying. Getting this backwards (treating ANY
# non-empty role as "not a field sample") was caught live: every row in a
# real extraction log carries role="Sample", so duplicate_all_samples and
# lfsm_frequency silently applied to ZERO rows -- see
# tests/test_run_composition.py::test_an_explicit_sample_role_is_still_a_field_sample.
# This vocabulary already lives elsewhere -- run_builder._noncount_codes() /
# _blank_codes() derive it from the Reference-Definition "pfas_qc_code" field
# (the single source the control charts and method profiles use), and
# _QC_LOT_FIELD / qc_labels.get_qc_label_map() carry their own copies for
# their own purposes. It CANNOT be derived the same way here: deriving from
# RefDefs needs `self._portal().bika_setup...`, i.e. Zope, and staying
# Zope-free is this module's entire reason to exist (see this module's
# docstring). So this is a second, hardcoded copy, by necessity, not an
# oversight -- but that means a QC code added to the RefDef vocabulary later
# must ALSO be added here, or it silently falls through to
# classify_sample_role()'s id-guess below. A role this set doesn't recognize
# is treated as a field sample, which is the SAFE direction under the
# direction rule (an unrecognized QC role gets duplicated / counted toward
# the LFSM interval -- more QC, not less) but is still worth knowing about;
# see GAPS.md Sec25.
_QC_ROLE_CODES = frozenset([
    "MB", "LRB", "MXB", "LFB", "LFSM", "LFSMD", "ICV", "CCV", "CCB", "DUP",
])


def is_field_sample(row):
    """True if `row` is a genuine field sample -- not a registered QC role,
    either explicitly (`row["role"]`, when it names a recognized QC code) or
    by id (classify_sample_role). duplicate_all_samples and lfsm_frequency
    only ever apply to field samples: doubling a registered MB or LFSM row,
    or counting it toward the LFSM interval, is not what "all samples run in
    duplicate" or "1 LFSM per N samples" mean."""
    explicit = (row.get("role") or u"").strip().upper()
    if explicit in _QC_ROLE_CODES:
        return False
    return not classify_sample_role(row)


def compose_sample_block(sample_rows, duplicate_all_samples, lfsm_frequency):
    """Expand the SAMPLES-token row list into the (row, marker) pairs
    run_builder actually injects, applying the two composition overrides:

      * duplicate_all_samples (bool-ish): every FIELD sample is immediately
        followed by a duplicate injection of itself.
      * lfsm_frequency (int-ish, "1 LFSM per N samples"): after every Nth
        FIELD sample -- counted on the ORIGINAL field-sample sequence, never
        inflated by the duplicate rows the first override may have just
        added, so "every 5 samples" means 5 samples whether or not
        duplicates are also on -- an extra LFSM marker is inserted.

    Returns a list of (row, marker):
        (row, "sample")    the original row, injected as-is.
        (row, "duplicate") a shallow copy of the row immediately before it,
                           carrying row["is_duplicate"] = True; not a new
                           sample identity (CLAUDE.md Sec3) -- a duplicate is
                           a repeat injection of the SAME registered sample.
        (None, "lfsm")     no row at all; the caller emits a QC injection
                           for code "LFSM".

    Identity when duplicate_all_samples is falsy and lfsm_frequency is
    None/0/negative: returns `[(row, "sample") for row in sample_rows]`
    unchanged -- see this module's docstring, SAFETY PROPERTY.
    """
    try:
        n = int(lfsm_frequency) if lfsm_frequency else 0
    except (TypeError, ValueError):
        n = 0

    out = []
    field_count = 0
    for row in sample_rows:
        out.append((row, "sample"))
        if not is_field_sample(row):
            continue
        if duplicate_all_samples:
            dup = dict(row)
            dup["is_duplicate"] = True
            out.append((dup, "duplicate"))
        field_count += 1
        if n > 0 and field_count % n == 0:
            out.append((None, "lfsm"))
    return out
