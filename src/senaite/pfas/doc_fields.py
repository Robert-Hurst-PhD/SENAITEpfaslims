# -*- coding: utf-8 -*-
"""The designer's field categories, once for every document.

the field list is broken down into Sample information,
Analysis information, Laboratory information, Preparer, Reviewer and
Director; categories the system's documents need beside those (inferred): Batch & worksheet, Quality control, Traceability, Logbook
entries, Deviations & corrections, Document control.

Every designable document (certificate, extraction log, QC Review, settings
report, labels, batch logbooks) lists its fields under these titles, in this
order; tests/test_doc_fields.py checks each field is in exactly one.

    grouped(fields, assign)  -> [(category, [(key, title, example)])]
    LAB_FIELDS, people(roles) -> the laboratory identity and signatory fields
                                 (same keys on every document)

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

SAMPLE = "Sample information"
ANALYSIS = "Analysis information"
QC = "Quality control"
BATCH = "Batch & worksheet"
TRACE = "Traceability"
ENTRIES = "Logbook entries"
DEVIATIONS = "Deviations & corrections"
LAB = "Laboratory information"
PREPARER = "Preparer"
REVIEWER = "Reviewer"
DIRECTOR = "Director"
DOCUMENT = "Document control"

CATEGORIES = (SAMPLE, ANALYSIS, QC, BATCH, TRACE, ENTRIES, DEVIATIONS, LAB,
              PREPARER, REVIEWER, DIRECTOR, DOCUMENT)

# the laboratory's identity: Print Settings (the certificate's own keys)
LAB_FIELDS = [
    ("lab_name", "Laboratory", "DEMO Laboratory"),
    ("lab_logo", "Logo", ""),
    ("lab_address", "Address", "1 Example Road, Example Town"),
    ("lab_phone", "Phone", "000-000-0000"),
    ("lab_email", "Email", "lab@example.org"),
    ("lab_accreditation", "Accreditation status", "ISO/IEC 17025:2017"),
]
LAB_IMAGES = ("lab_logo",)

# examples are visibly DEMO: the designer refuses fixed text that copies an
# example value, so an example must not be a word a layout would type
_ROLE = {"preparer": (PREPARER, "Preparer", "AN1", "DEMO chemist", "DEMO B.Sc."),
         "reviewer": (REVIEWER, "Reviewer", "AN2", "DEMO QA officer", "DEMO M.Sc."),
         "director": (DIRECTOR, "Laboratory Director", "AN3", "DEMO director", "DEMO Ph.D.")}


def people(roles=("preparer", "reviewer", "director")):
    """[(category, [fields])] for each signatory: name, title, credentials,
    date (not the director's) and signature -- the keys the certificate uses
    (preparer_name, ..., director_signature)."""
    out = []
    for role in roles:
        cat, title, name, job, cred = _ROLE[role]
        fs = [("%s_name" % role, title, name),
              ("%s_title" % role, "%s title" % title, job),
              ("%s_credentials" % role, "%s credentials" % title, cred)]
        if role != "director":
            fs.append(("%s_date" % role, "%s date" % title, "2026-10-05"))
        fs.append(("%s_signature" % role, "%s signature" % title, ""))
        out.append((cat, fs))
    return out


def people_images(roles=("preparer", "reviewer", "director")):
    return tuple("%s_signature" % r for r in roles)


def grouped(fields, assign):
    """[(category, [(key, title, example)])] in CATEGORIES order, empty
    categories left out. `assign`: {key: category}. A field without a
    category, or with one not in CATEGORIES, raises ValueError: no field may
    drop out of the designer."""
    by = dict((c, []) for c in CATEGORIES)
    for f in fields:
        cat = assign.get(f[0])
        if cat not in by:
            raise ValueError("field %s has no designer category (%r)" % (f[0], cat))
        by[cat].append(f)
    return [(c, by[c]) for c in CATEGORIES if by[c]]
