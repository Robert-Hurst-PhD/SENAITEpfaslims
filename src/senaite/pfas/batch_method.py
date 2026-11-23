# -*- coding: utf-8 -*-
"""A batch's method: one resolver for every page.

Every page reads a batch's method here, so no two pages judge one batch by
different methods. The sources, in the lab's order (core first):

    1. analyses   the method on the batch's analyses -- what core reports
    2. worksheet  core's worksheet Method, set when its samples are added
                  (so a worksheet that holds none yet names its method)
    3. core       core's Batch Method
    4. session    the guided extraction's session
    5. 252        the extraction record
    6. manifest   the Run Builder's run manifest
    7. study      a study worksheet's method study (study_runs; it holds no
                  sample, so nothing above names its method before extraction)

The first source that names a method wins; every source that names a
DIFFERENT one is a conflict, shown on Data Review and the Extraction Guide.

    pick(sources)            pure: (method id, [(source, other method)])
    resolve(batch)           (method id, conflicts) for a core Batch
    for_worksheet(ws)        a worksheet's method, for every page that asks
    of(context)              the method of a page's context: a worksheet's,
                             a client Batch's, else u""
"""
from __future__ import absolute_import, unicode_literals

import json

ORDER = ("analyses", "worksheet", "core", "session", "252", "manifest", "study")
LABELS = {"analyses": u"the batch's analyses", "worksheet": u"the worksheet's Method (SENAITE)",
          "core": u"the batch's Method (SENAITE)",
          "session": u"the guided extraction", "252": u"the extraction record",
          "manifest": u"the run manifest",
          "study": u"the method study"}
_MANIFEST_KEY = u"senaite.pfas.run_manifest"


def pick(sources):
    """sources: {name: method id or "" or a list of ids (the analyses)}.
    A list of several methods is itself a conflict and names none."""
    winner, conflicts = u"", []
    for name in ORDER:
        value = sources.get(name)
        if isinstance(value, (list, tuple, set)):
            found = sorted(set(v for v in value if v))
            if len(found) > 1:
                conflicts.append((name, u", ".join(found)))
                continue
            value = found[0] if found else u""
        if not value:
            continue
        if not winner:
            winner = value
        elif value != winner:
            conflicts.append((name, value))
    return winner, conflicts


def _named_method(data):
    return (data or {}).get("method_id") or (data or {}).get("method") or u""


def _annotation_method(batch, key):
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(batch).get(key)
    try:
        data = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return u""
    return _named_method(data) if isinstance(data, dict) else u""


def sources(batch, home=None):
    """The method each source names, for a client Batch or a Worksheet (the
    extraction batch): the analyses of the container's samples,
    the client Batch's core Method, the extraction record's session and
    Extraction Log (on the worksheet), the prep log and manifest (on the
    Batch). `home`: the worksheet the caller came from, which holds the
    extraction record and whose own Method counts; without it a client
    Batch's is looked for among its samples' analyses (every analysis woken:
    seconds per Batch)."""
    from senaite.pfas import extraction_batch
    from senaite.pfas.core_fields import samples_of
    from senaite.pfas.method_bridge import profile_id_for_method
    is_ws = extraction_batch.is_worksheet(batch)
    client_batch = extraction_batch.linked_batch(batch) if is_ws else batch
    home = batch if is_ws else (home if home is not None else extraction_batch.home(batch))
    out = {}
    methods = set()
    from senaite.pfas.sample_method import reported_analyses
    for sample in samples_of(batch):
        for an in reported_analyses(sample):
            m = an.getMethod()
            if m is not None:
                methods.add(profile_id_for_method(m))
    out["analyses"] = sorted(m for m in methods if m)
    # the worksheet's own Method: the worksheet itself, or the one the
    # caller came from (home() may be the client Batch)
    ws = batch if is_ws else (home if extraction_batch.is_worksheet(home) else None)
    wm = ws.getMethod() if ws is not None else None
    out["worksheet"] = profile_id_for_method(wm) if wm is not None else u""
    m = client_batch.getMethod() if client_batch is not None and hasattr(client_batch, "getMethod") else None
    out["core"] = profile_id_for_method(m) if m else u""
    from senaite.pfas.browser.extraction_guide import _load_session
    out["session"] = (_load_session(home).get("method_id") if home is not None else u"") or u""
    from senaite.pfas import extraction_store
    out["252"] = _named_method(extraction_store.load_table(home)) if home is not None else u""
    out["manifest"] = _annotation_method(client_batch, _MANIFEST_KEY) if client_batch is not None else u""
    out["study"] = u""
    if is_ws:
        from senaite.pfas import study_runs
        out["study"] = (study_runs.load_run(batch) or {}).get("method_id") or u""
    return out


def resolve(batch, home=None):
    """(method id, [(source label, other method)]) for a core Batch; `home`,
    the worksheet holding its extraction record when the caller knows it."""
    if batch is None:
        return u"", []
    winner, conflicts = pick(sources(batch, home))
    return winner, [(LABELS[n], v) for n, v in conflicts]


def for_worksheet(ws):
    """A worksheet's method (the lab's rule): its client Batch's by resolve(),
    the worksheet holding the extraction record; else, or when that names
    none, the worksheet's own Method; else the method its analyses carry
    when they agree on one (analyses that disagree name none, as pick() has
    it); else a study run's. u"" when nothing names one."""
    from senaite.pfas import extraction_batch
    from senaite.pfas.method_bridge import profile_id_for_method
    batch = None
    for sample in extraction_batch.samples_on(ws):        # by the catalog, never each analysis
        batch = sample.getBatch()
        if batch is not None:
            break
    if batch is not None:
        mid = resolve(batch, home=ws)[0]
        if mid:
            return mid
    m = ws.getMethod()
    if m:
        return profile_id_for_method(m) or u""
    found = set()
    for an in ws.getAnalyses() or []:
        am = an.getMethod()
        if am is not None:
            found.add(profile_id_for_method(am) or u"")
    found.discard(u"")
    if len(found) > 1:
        return u""
    if found:
        return found.pop()
    from senaite.pfas import study_runs
    return (study_runs.load_run(ws) or {}).get("method_id") or u""


def of(context):
    """The method of a page's context: a worksheet's by for_worksheet, a
    client Batch's by resolve(); u"" opened on anything else."""
    kind = getattr(context, "portal_type", "")
    if kind == "Worksheet":
        return for_worksheet(context)
    if kind != "Batch":
        return u""
    return resolve(context)[0]
