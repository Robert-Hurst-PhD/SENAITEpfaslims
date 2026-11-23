# -*- coding: utf-8 -*-
"""Samples named by the laboratory's own sample ID in a report package.

A package goes to one client, and the run it draws from may hold other
clients' samples. Its parts beyond the certificate name every sample, in a
list of injections, a chromatogram or a batch record, by the laboratory's
own sample ID, never a client's sample ID, so no client's identifier reaches
another client. A run whose injections were named by a client sample ID
prints them under the laboratory's ID; nothing is left out or relabelled
otherwise. What is printed changes, never what is stored.

    lab_names(samples)            {client sample id: lab sample id}
    by_lab_id(name, names, role)  an injection or sample name, renamed
    joined(text, names)           a ", "-joined list of names, renamed
    qc_review_sections(found, names)   the QC Review sections a package prints
    batch_record_data(data, names)     the batch record's printed data

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import re

# the separators between the parts of an injection name: the naming scheme's
# "_", and the space an instrument's own name may carry
SEPARATORS = ("_", " ")
# the run's own injections, never made from a client's sample: the
# calibrators, the instrument checks and the blanks (qc_engine's run-check
# and blank roles, and the names a method gives its checks)
NOT_FROM_A_SAMPLE = frozenset((u"CAL", u"ICV", u"CCV", u"CCB", u"QCS", u"CCC", u"MB", u"LRB", u"MXB",
                               u"LFB", u"LCS", u"FRB", u"BLANK", u"SOLVENT"))
# the batch record's tables and the columns of each that name a sample or
# an injection
BATCH_RECORD_NAMES = {"extracted": ("name", "made_from"), "spikes": ("sample", "parent"),
                      "dilutions": ("from", "injection"), "homogenisation": ("sample",)}


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value or u""


def lab_names(samples):
    """{client sample id: lab sample id} from [(lab sample id, client sample
    id)]. A client sample id two samples share names both, "A / B"; a blank
    one, or one that is its own lab sample id, is left out."""
    found = {}
    for lab_id, client_id in samples or ():
        lab_id, client_id = _text(lab_id).strip(), _text(client_id).strip()
        if not lab_id or not client_id or client_id == lab_id:
            continue
        found.setdefault(client_id, set()).add(lab_id)
    return dict((cid, u" / ".join(sorted(ids))) for cid, ids in found.items())


def _word(part):
    """A name part as a role reads: its letters before a level ("CAL-1")."""
    return part.strip().upper().split(u"-")[0]


def _names_a_run_check(parts):
    return any(_word(p) in NOT_FROM_A_SAMPLE for p in parts)


def by_lab_id(name, names, role=None):
    """`name` with the client sample id it names replaced by the lab sample
    id: the whole name, or a name that starts with the id and a separator
    (DEMO-1_DIL10). A name the run classed (`role`) as a calibrator, an
    instrument check or a blank, or one whose parts read as one, is never
    renamed, whatever a client called a sample; neither is a part inside a
    name. Anything else is returned as it is."""
    text = _text(name)
    if not text or not names:
        return text
    if role and _word(_text(role)) in NOT_FROM_A_SAMPLE:
        return text
    if text in names:
        return text if (not role and _names_a_run_check([text])) else names[text]
    for cid in sorted(names, key=len, reverse=True):
        for sep in SEPARATORS:
            if text.startswith(cid + sep):
                rest = re.split(u"[_ ]", text[len(cid) + 1:])
                return text if _names_a_run_check(rest) else names[cid] + text[len(cid):]
    return text


def joined(text, names):
    """A ", "-joined list of names, each renamed."""
    text = _text(text)
    if not text or not names:
        return text
    return u", ".join(by_lab_id(n, names) for n in text.split(u", "))


def _rows(rows, keys, names, role_key=None):
    out = []
    for row in rows or []:
        row = dict(row)
        for k in keys:
            if k in row:
                row[k] = by_lab_id(row[k], names, row.get(role_key) if role_key else None)
        out.append(row)
    return out


def qc_review_sections(found, names):
    """A copy of the QC Review's sections (qc_review_report.designed_sections)
    with every injection named by the lab sample id: the measurements, the
    flagged ones, the run against its plan and the spikes waiting for a
    level. The other sections name no client sample."""
    out = copy.deepcopy(found or {})
    if not names:
        return out
    for key in ("injections", "exceptions"):
        if key in out:
            out[key] = _rows(out[key], ("injection_name",), names, "qc_type")
    plan = out.get("run_vs_plan")
    if isinstance(plan, dict):
        for key in ("planned", "actual", "not_run", "unplanned"):
            if isinstance(plan.get(key), list):
                plan[key] = [by_lab_id(n, names) if not isinstance(n, dict) else n for n in plan[key]]
    spikes = out.get("spike_qc")
    if isinstance(spikes, dict) and spikes.get("pending_spikes"):
        spikes["pending_spikes"] = _rows(spikes["pending_spikes"], ("injection",), names)
    return out


def batch_record_data(data, names):
    """A copy of the batch record's printed data (report_documents
    .batch_record_data) with every sample and injection named by the lab
    sample id. The record and its hash are not touched: only the print."""
    out = dict(data or {})
    if not names:
        return out
    for table, keys in BATCH_RECORD_NAMES.items():
        if table in out:
            # what was extracted carries its role
            out[table] = _rows(out[table], keys, names, "role" if table == "extracted" else None)
    return out
