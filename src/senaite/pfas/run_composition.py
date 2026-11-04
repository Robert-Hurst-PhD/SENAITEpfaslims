# -*- coding: utf-8 -*-
"""
Pure QC-COMPOSITION transforms for the LC-MS run builder
(senaite.pfas.browser.run_builder).

A QAPP can override which injections a run contains and how often ("all
samples run in duplicate", "LFSMs get run in more regular intervals"), apart
from the numeric criteria, which resolve through senaite.pfas.ruleset. Kept
Zope-free so it loads and tests by path; run_builder.py imports Zope.

Not here: "an additional surrogate is used". The surrogate-to-IS map is a
method-owned fact (Sec3), never overridden per QAPP.

SAFETY PROPERTY (both transforms are identity on their defaults):
duplicate_all_samples=None/False and lfsm_frequency=None/0 make
compose_sample_block() return `[(row, "sample") for row in sample_rows]`,
the input in order: a batch with no project builds the plain sequence.
tests/test_run_composition.py pins this.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals

import re

# MB is matched as a token, not a substring ("MB" sits inside unrelated
# words); tokens split on any non-alphanumeric run, so the run builder's own
# hyphenated ids (FDA_32PFAS-MB-260923-01) match.
_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")


def classify_sample_role(row):
    """The QC role a registered sample `row` plays, guessed from its id, or
    "" if it names no recognizable QC role (i.e. it is a genuine field
    sample). The one definition shared by run_builder's redundant-QC
    suppression and is_field_sample().

    A duplicate is written "LFSM Mid Duplicate" at least as often as
    "LFSMD" on real sample ids, so LFSMD is matched on either spelling.
    """
    raw = (row.get("client_sample_id") or row.get("sample_id") or u"")
    sid = raw.upper()
    if "LFSMD" in sid or ("LFSM" in sid and "DUP" in sid):
        return "LFSMD"
    if "LFSM" in sid:
        return "LFSM"
    if "MB" in _TOKEN_SPLIT.split(sid):
        return "MB"
    for code in ("ICV", "CCV", "LFB", "CCB"):
        if code in sid:
            return code
    return u""


# The QC roles in the extraction log's `sample_type`/`role` column
# (row["role"]) that make a row not a field sample. An ordinary field sample
# carries "Sample", not blank; any other value falls through to the id guess
# (classify_sample_role). The vocabulary's source is the Reference
# Definition "pfas_qc_code" field (run_builder._noncount_codes()), which needs
# Zope: a code added there must be added here too. An unknown role counts as
# a field sample, the safe direction (more QC, not less).
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
    if explicit == u"SAMPLE":
        return True          # the record says so; its id is never read
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
                           carrying row["is_duplicate"] = True: a repeat
                           injection of the same registered sample.
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
