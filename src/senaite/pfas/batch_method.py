# -*- coding: utf-8 -*-
"""A batch's method: one resolver for every page.

The method was read from up to six places in two different orders, and they
already disagreed on a live batch (the extraction session said EPA 537.1, the
logbooks and run manifest FDA 32-PFAS), so the Extraction Guide and the EDD
judged one batch by different methods. The lab chose core first:

    1. analyses   the method on the batch's analyses -- what core reports
    2. core       core's Batch Method
    3. session    the guided extraction's session
    4. 252        the Extraction Log (FM-ENV-003)
    5. 251        the Calibration Prep Log (FM-ENV-002)
    6. manifest   the Run Builder's run manifest
    7. study      a study worksheet's method study (study_runs; it holds no
                  sample, so nothing above names its method before extraction)

The first source that names a method wins; every source that names a
DIFFERENT one is a conflict, shown on Data Review and the Extraction Guide.

    pick(sources)            pure: (method id, [(source, other method)])
    resolve(batch)           (method id, conflicts) for a core Batch
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.batch_method")

ORDER = ("analyses", "core", "session", "252", "251", "manifest", "study")
LABELS = {"analyses": u"the batch's analyses", "core": u"the batch's Method (SENAITE)",
          "session": u"the guided extraction", "252": u"the Extraction Log",
          "251": u"the Calibration Prep Log", "manifest": u"the run manifest",
          "study": u"the method study"}
_ANNOTATIONS = {"252": u"senaite.pfas.logbook.252", "251": u"senaite.pfas.logbook.251",
                "manifest": u"senaite.pfas.run_manifest"}


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


def _annotation_method(batch, key):
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(batch).get(key)
        data = json.loads(raw) if raw else {}
        return data.get("method_id") or data.get("method") or u""
    except Exception:                                       # noqa: BLE001
        return u""


def sources(batch):
    """The method each source names, for a client Batch or a Worksheet (the
    extraction batch, D1 2026-10-06): the analyses of the container's samples,
    the client Batch's core Method, the extraction record's session and
    Extraction Log (on the worksheet), the prep log and manifest (on the
    Batch)."""
    from senaite.pfas import extraction_batch
    from senaite.pfas.core_fields import samples_of
    from senaite.pfas.method_bridge import profile_id_for_method
    is_ws = extraction_batch.is_worksheet(batch)
    client_batch = extraction_batch.linked_batch(batch) if is_ws else batch
    home = batch if is_ws else extraction_batch.home(batch)
    out = {}
    methods = set()
    try:
        from senaite.pfas.sample_method import reported_analyses
        for sample in samples_of(batch):
            for an in reported_analyses(sample):
                m = an.getMethod()
                if m is not None:
                    methods.add(profile_id_for_method(m))
    except Exception:                                       # noqa: BLE001
        logger.warning("batch analyses unreadable", exc_info=True)
    out["analyses"] = sorted(m for m in methods if m)
    try:
        m = client_batch.getMethod() if client_batch is not None and hasattr(client_batch, "getMethod") else None
        out["core"] = profile_id_for_method(m) if m else u""
    except Exception:                                       # noqa: BLE001
        out["core"] = u""
    try:
        from senaite.pfas.browser.extraction_guide import _load_session
        out["session"] = (_load_session(home).get("method_id") if home is not None else u"") or u""
    except Exception:                                       # noqa: BLE001
        out["session"] = u""
    for name, key in _ANNOTATIONS.items():
        obj = home if name == "252" else client_batch
        out[name] = _annotation_method(obj, key) if obj is not None else u""
    out["study"] = u""
    if is_ws:
        from senaite.pfas import study_runs
        out["study"] = (study_runs.load_run(batch) or {}).get("method_id") or u""
    return out


def resolve(batch):
    """(method id, [(source label, other method)]) for a core Batch."""
    if batch is None:
        return u"", []
    winner, conflicts = pick(sources(batch))
    return winner, [(LABELS[n], v) for n, v in conflicts]
