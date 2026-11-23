# -*- coding: utf-8 -*-
"""Making a dilution or re-injection Data Review asked for, in one place.

A retest that needs a dilution is asked for at Data Review (a run request,
extraction_batch.REQUESTS_KEY on the worksheet: the one store of what was
asked and how it was made). It is made at the bench, from Run Builder's
step 4 or from the guided extraction's optional Dilutions stage, through
the same dialog (browser/templates/dilution_make_macros.pt, macro
make-dialog) and
the same rules (make): the vial's prep (extract taken, final volume, the
diluent lot, how the internal standard and the surrogate were handled and
their lots, the fold its volumes make kept beside the one asked for), then
written to the
extraction record under the method profile's dilution rules
(sample_table.append_dilution: its routes, largest fold, aliquot and client
approval).

    listed(b)              the worksheet's requests, as both pages list them
    options(portal)        the dialog's choices (diluent and standard lots,
                           the handlings)
    make(b, form, who, at, settings) -> error text or None

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.dilution_make")


def listed(b):
    """Every dilution and re-injection asked for on worksheet `b`, open or
    made, with what the tables show: "asked" in words and whether the
    prep's volumes make the fold asked for ("matches")."""
    from senaite.pfas import extraction_batch as eb
    if b is None or not eb.is_worksheet(b):
        return []
    out = []
    for r in eb.load_requests(b):
        prep = r.get("prep") or {}
        out.append(dict(r, asked=(u"Dilution 1:%s" % r.get("fold")) if r.get("kind") == u"dilution"
                        else u"Re-injection", matches=prep.get("matches")))
    return out


def options(portal):
    """{"diluent", "standards", "handlings"}: the usable reagent and
    prepared standard lots today, as (uid, "name · lot"), and how a labelled
    standard may be handled."""
    from senaite.pfas import extraction_batch as eb
    from senaite.pfas import lab_time
    from senaite.pfas.browser.bench_inventory import PREPARED, REAGENT, usable_lots
    try:
        items = usable_lots(portal, lab_time.today().isoformat())
    except Exception as exc:                                # noqa: BLE001
        logger.warning("usable lots: %s", exc)
        items = []

    def lots(want):
        return [(i["uid"], u"%s · %s" % (i.get("name") or u"", i.get("lot_number") or u""))
                for i in items if i.get("kind") == want]
    return {"diluent": lots(REAGENT), "standards": lots(PREPARED), "handlings": eb.HANDLINGS}


def make(b, form, who, at, settings):
    """Mark the request `form["request"]` of worksheet `b` made: a dilution
    with its prep (refused while incomplete), and
    its row written to the extraction record under `settings`, the method's
    dilution rules with the project's overrides (a re-prepared aliquot is
    judged in the batch it is re-prepared in, so without them). Returns the
    refusal's text, or None once written."""
    from senaite.pfas import extraction_batch as eb
    from senaite.pfas import extraction_store, sample_table
    if b is None or not eb.is_worksheet(b):
        return u"No such worksheet."
    rid = (form.get("request") or u"").strip()
    requests = eb.load_requests(b)
    req = next((r for r in requests if r.get("id") == rid), None)
    prep = None
    if req is not None and req.get("kind") == u"dilution":
        prep = eb.prep_from_form(form, rid)
        problems = eb.prep_problems(prep, req.get("fold"))
        if problems:
            return problems[0]
    requests, req, error = eb.mark_made(requests, rid, who, at, prep=prep)
    if error:
        return error
    if req["kind"] == u"dilution":
        log = dict(extraction_store.load_table(b))
        route = sample_table.route_key(req.get("route"))
        rows, derr = sample_table.append_dilution(
            log.get("samples"), req["injection"], req["new_injection"], req["fold"], who, at,
            route=route, settings=None if route == u"reprep" else settings)
        if derr:
            return derr
        log["samples"] = rows
        extraction_store.save_table(b, log)
    eb.save_requests(b, requests)
    return None
