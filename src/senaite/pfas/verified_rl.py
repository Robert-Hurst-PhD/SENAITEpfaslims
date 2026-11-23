# -*- coding: utf-8 -*-
"""Each result's reporting limit and MDL, frozen when its worksheet is
verified.

The RL a certificate prints is the method's live setting
(report_limits.limits_for): a typed RL, else the lowest calibrator times
the salt factor. A later change to the method (a salt factor entered, an RL
raised, an MDL study approved) must not change what a verified result was
reported against, so a reissue prints the RL and the MDL the result had when
its worksheet was verified: the J band (between the MDL and the RL) is drawn
from them too. They are kept on the result itself, an annotation of the
analysis beside its stamped qualifier codes: {"rl", "mdl", "unit",
"rl_source", "frozen_at", "worksheet", "method_id"}, the base limits before a
dilution scales them, on the run's acid basis as the certificate prints
them. A certificate reads them through report_limits.limits_with_frozen.
Write-once: a second verification keeps the first. A result verified before
the freeze existed has none and prints the live limits; one frozen before
the MDL was kept has no "mdl" and prints the live MDL.

A worksheet verified before either freeze is filled afterwards by
tools/freeze_verified_limits.py (fill_missing): the limits as they are when
it runs, marked "backfilled", and never a value already frozen.

Beside them, the worksheet keeps its not-run statement, frozen at the same
verification: each QC type the method requires every run that the run did
not hold, with the deviation that released it ([{"qc_type", "dev_id"}],
data_review.qc_types_not_run), an annotation of the worksheet under
NOT_RUN_KEY: {"not_run", "frozen_at", "worksheet"}. An empty list is
frozen too: nothing missing at verification is a fact, not an absence. A
certificate drawn later prints the frozen statement (coa_sections); a gate
that could not be read freezes nothing, and the certificate reads it live.

Nothing here touches a signed record: the batch record's hash covers its
own stored parts, not the analyses or the worksheet's other annotations.

Pure core (payload, store_once, fill_missing, read_store, freeze_analyses)
under plain Python; freeze_worksheet and frozen_for are the ZODB shells.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import logging

logger = logging.getLogger("senaite.pfas.verified_rl")

KEY = u"senaite.pfas.verified_rl"


def payload(lim, at, worksheet_id=u"", method_id=u""):
    """What is frozen of one result's limits (report_limits.limits_for)."""
    lim = lim or {}
    return {"rl": lim.get("rl"), "mdl": lim.get("mdl"), "unit": lim.get("unit") or u"",
            "rl_source": lim.get("rl_source") or u"",
            "frozen_at": at, "worksheet": worksheet_id or u"", "method_id": method_id or u""}


def read_store(store):
    """The frozen payload in `store` (a mapping), or None when there is none
    or it cannot be read."""
    raw = store.get(KEY) if store is not None else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and "rl" in data else None


def store_once(store, data):
    """Write `data` unless a payload is already there; the payload kept."""
    kept = read_store(store)
    if kept is not None:
        return kept
    store[KEY] = json.dumps(data)
    return data


def _freeze_once(store, data):
    """What store_once wrote: u"limits", or None when a payload was kept."""
    return u"limits" if store_once(store, data) is data else None


# what fill_missing adds: the whole payload, or the MDL beside a frozen RL
FILLED_ALL, FILLED_MDL = u"limits", u"mdl"


def fill_planned(store, data):
    """What fill_missing would add to `store`, writing nothing: FILLED_ALL
    when nothing is frozen, FILLED_MDL when an RL is frozen without an MDL,
    else None. A store that holds something unreadable is left alone."""
    if store is not None and store.get(KEY) and read_store(store) is None:
        return None
    kept = read_store(store)
    if kept is None:
        return FILLED_ALL
    return FILLED_MDL if "mdl" not in kept else None


def fill_missing(store, data):
    """Freeze, after the fact, what a verified result lacks, never changing
    a value already frozen: the whole payload where none is (marked
    "backfilled"), else the MDL beside a frozen RL that has none (its time
    as "mdl_backfilled_at"). Returns what was added (fill_planned)."""
    planned = fill_planned(store, data)
    if planned == FILLED_ALL:
        store[KEY] = json.dumps(dict(data, backfilled=True))
    elif planned == FILLED_MDL:
        kept = read_store(store)
        kept.update(mdl=data.get("mdl"), mdl_backfilled_at=data.get("frozen_at"))
        store[KEY] = json.dumps(kept)
    return planned


def freeze_analyses(analyses, limits_of, store_of, at, worksheet_id=u"", write=None):
    """Freeze each analysis' limits; how many were written. `limits_of(an)`:
    (limits_for's dict, method id), or None when the result's method cannot
    be named (nothing is frozen: the certificate keeps the live limit);
    `store_of(an)`: its annotation mapping; `write(store, payload)`: what it
    wrote, or None (default: write-once at verification)."""
    write = write or _freeze_once
    written = 0
    for an in analyses or []:
        found = limits_of(an)
        if not found:
            continue
        lim, method_id = found
        if write(store_of(an), payload(lim, at, worksheet_id, method_id)):
            written += 1
    return written


# ── The not-run statement, one per worksheet ────────────────────────────────

NOT_RUN_KEY = u"senaite.pfas.verified_not_run"
FILLED_NOT_RUN = u"not_run"


def not_run_payload(items, at, worksheet_id=u""):
    """What is frozen of a worksheet's not-run statement: [{"qc_type",
    "dev_id"}] (qc_deviation.not_run), each QC type once."""
    clean = [{"qc_type": (i or {}).get("qc_type") or u"", "dev_id": (i or {}).get("dev_id") or u""}
             for i in items or [] if (i or {}).get("qc_type")]
    return {"not_run": clean, "frozen_at": at, "worksheet": worksheet_id or u""}


def read_not_run(store):
    """The frozen not-run payload in `store`, or None when there is none or
    it cannot be read."""
    raw = store.get(NOT_RUN_KEY) if store is not None else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("not_run"), list):
        return None
    return data


def not_run_planned(store, data=None):
    """FILLED_NOT_RUN when nothing is frozen in `store`, else None; a store
    holding something unreadable is left alone. Writes nothing."""
    if store is None or store.get(NOT_RUN_KEY):
        return None
    return FILLED_NOT_RUN


def store_not_run_once(store, data):
    """Write the payload at verification unless one is there: FILLED_NOT_RUN
    when written, else None (the first freeze stands)."""
    if not_run_planned(store) is None:
        return None
    store[NOT_RUN_KEY] = json.dumps(data)
    return FILLED_NOT_RUN


def fill_not_run(store, data):
    """Freeze after the fact, marked "backfilled", where nothing is frozen;
    never a value already frozen. Returns what not_run_planned gave."""
    planned = not_run_planned(store)
    if planned:
        store[NOT_RUN_KEY] = json.dumps(dict(data, backfilled=True))
    return planned


def freeze_not_run(store, read_items, at, worksheet_id=u"", write=None):
    """Freeze a worksheet's not-run statement into `store`. `read_items()`:
    its [{"qc_type", "dev_id"}]; one that raises freezes nothing (a gate not
    read is never "nothing missing"). `write`: store_not_run_once by
    default; the backfill passes fill_not_run, or not_run_planned for a dry
    run. Returns what `write` returned, or None."""
    if not_run_planned(store) is None:
        return None
    try:
        items = read_items()
    except Exception as exc:                                # noqa: BLE001
        logger.error("not-run freeze of %s: %s", worksheet_id or u"?", exc)
        return None
    return (write or store_not_run_once)(store, not_run_payload(items, at, worksheet_id))


# ── ZODB shells ─────────────────────────────────────────────────────────────

def _sample_limits(portal, sample):
    """(profile, matrix, method id) a certificate of `sample` reads its
    limits from (coa_sections: the sample's method, its matrix, its
    project's specs), or None when its method cannot be named."""
    from senaite.pfas.method_profile_store import get_profile
    from senaite.pfas.project_specs import profile_for_batch
    from senaite.pfas.report_limits import canonical_matrix
    from senaite.pfas.sample_method import identify_from, project_added
    from bika.lims import api
    from senaite.pfas.browser.coa_sections import _EXCLUDED_STATES
    # the analyses the certificate reports (coa_sections._analyses)
    analyses = []
    for an in sample.objectValues():
        if getattr(an, "portal_type", "") != "Analysis":
            continue
        try:
            if an.getHidden() or an.isRetested():
                continue
        except Exception:                                   # noqa: BLE001
            pass
        if api.get_review_status(an) in _EXCLUDED_STATES:
            continue
        analyses.append(an)
    method, problem = identify_from(analyses, project_added(sample))
    if problem or method is None:
        return None
    method_id = method.getMethodID()
    profile = get_profile(portal, method_id) or {}
    matrix = canonical_matrix(profile, sample.getSampleTypeTitle())
    profile = profile_for_batch(portal, sample.getBatch(), method_id, matrix) or profile
    return profile, matrix, method_id


def freeze_worksheet(portal, ws, write=None, at=None):
    """Freeze the limits of every result on a worksheet being verified;
    how many were written. Each result's limits are the certificate's: its
    run's acid basis decides the default RL as there. Never raises for one
    result: it is logged and the rest are frozen. `write`: as
    freeze_analyses (the backfill passes fill_missing, or fill_planned for a
    dry run); `at`: the time recorded, now by default."""
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.browser.run_builder import analysis_acid_basis
    from senaite.pfas.report_limits import limits_for
    by_sample, acid_cache = {}, {}

    def limits_of(an):
        try:
            sample = an.getRequest()
            uid = sample.UID()
            if uid not in by_sample:
                by_sample[uid] = _sample_limits(portal, sample)
            found = by_sample[uid]
            if found is None:
                return None
            profile, matrix, method_id = found
            kw = an.getKeyword()
            acid = [a.upper() for a in analysis_acid_basis(an, acid_cache)]
            return limits_for(profile, matrix, kw,
                              acid_basis=[kw] if kw.upper() in acid else None), method_id
        except Exception as exc:                            # noqa: BLE001
            logger.error("verified RL of %s: %s", getattr(an, "getId", lambda: "?")(), exc)
            return None

    analyses = [a for a in (ws.getAnalyses() or []) if getattr(a, "portal_type", "") == "Analysis"]
    at = at or datetime.datetime.utcnow().isoformat() + u"Z"
    return freeze_analyses(analyses, limits_of, IAnnotations, at, ws.getId(), write)


def freeze_worksheet_not_run(ws, read_items, write=None, at=None):
    """Freeze the not-run statement of a worksheet being verified (its
    annotations); `read_items`, `write`: as freeze_not_run."""
    from zope.annotation.interfaces import IAnnotations
    at = at or datetime.datetime.utcnow().isoformat() + u"Z"
    return freeze_not_run(IAnnotations(ws), read_items, at, ws.getId(), write)


def frozen_not_run_for(ws):
    """The worksheet's frozen not-run payload, or None (a read: nothing is
    written)."""
    try:
        from zope.annotation.interfaces import IAnnotations
        return read_not_run(IAnnotations(ws))
    except Exception as exc:                                # noqa: BLE001
        logger.warning("frozen not-run of %s: %s", getattr(ws, "getId", lambda: "?")(), exc)
        return None


def frozen_for(analysis):
    """The result's frozen limits, or None (a read: nothing is written)."""
    try:
        from zope.annotation.interfaces import IAnnotations
        return read_store(IAnnotations(analysis))
    except Exception as exc:                                # noqa: BLE001
        logger.warning("frozen RL of %s: %s", getattr(analysis, "getId", lambda: "?")(), exc)
        return None
