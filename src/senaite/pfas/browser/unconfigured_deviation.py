# -*- coding: utf-8 -*-
"""@@pfas-unconfigured-deviation: POST {"worksheet_uid"}, the worker asks,
once it has pushed a run, for the deviation its unset QC criteria call for
(qc_deviation.ensure_deviation, through Data Review's own reading of the
QC Summary, so the gaps and their signature are the gate's). Idempotent; a
QAO e-mail that never went is tried again. JSON {"ok", "dev_id"}: the
deviation's id, "" when the run's criteria are all set.

A run's deviation is raised here and not when Data Review renders: a page
GET does not write. The worker's notice tick (@@pfas-notice-reminders) also
asks for every open worksheet with a run (raise_for_open_worksheets): a cell
the live qualifier library leaves not judged can arise after the push."""
from __future__ import absolute_import, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.unconfigured_deviation")

# the worksheets still under review: one submitted or past has passed the
# gate, which a result not judged holds
OPEN_STATES = ("open", "attachment_due")

# worksheet uid -> (what the last pass judged it on, when). The tick judged
# every open worksheet's QC Summary every 15 minutes, a minute of server
# time; one is judged again only when the worksheet, its run in the QC
# store or the configuration (any save Configuration History records, the
# qualifier library among them) changed since, and every FULL_PASS_SECONDS
# whatever changed. A run just pushed is judged by the worker's own call.
_JUDGED = {}
FULL_PASS_SECONDS = 6 * 3600


def _config_mark(portal):
    """The last configuration save on record; a fresh object (never equal)
    when it cannot be read."""
    try:
        from senaite.pfas.config_history import _btree
        tree = _btree(portal, create=False)
        return tree.maxKey() if tree else None
    except Exception:                                       # noqa: BLE001
        return object()


def _run_mark(ws_id):
    """The run of a worksheet as the QC store holds it: its record's last
    update and its QC rows (the last id, how many); a fresh object when the
    store cannot be read."""
    try:
        import sqlite3
        from senaite.pfas.qc.store import DEFAULT_DB_PATH
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            return tuple(conn.execute(
                "SELECT (SELECT updated_at FROM batches WHERE batch_id=?), "
                "(SELECT MAX(id) FROM qc_results WHERE batch_id=?), "
                "(SELECT COUNT(*) FROM qc_results WHERE batch_id=?)", (ws_id, ws_id, ws_id)).fetchone())
        finally:
            conn.close()
    except Exception:                                       # noqa: BLE001
        return object()


def _mark(ws, config):
    ann = getattr(ws, "__annotations__", None)
    return (getattr(ws, "_p_mtime", None), getattr(ann, "_p_mtime", None), _run_mark(ws.getId()), config)


def unchanged(uid, mark, now):
    """True when the worksheet was judged on this same mark within the full-pass time."""
    seen = _JUDGED.get(uid)
    return seen is not None and seen[0] == mark and now - seen[1] < FULL_PASS_SECONDS


def raise_for_open_worksheets(portal, request):
    """Raise the deviation of each open worksheet whose run is on record and
    holds a result not judged (PFASDataReviewView.raise_unconfigured_deviation,
    idempotent); the ids of the deviations found or filed. One worksheet
    that cannot be read is logged and the rest are still asked."""
    import time
    from bika.lims import api
    from senaite.pfas import retired
    from senaite.pfas.browser.data_review import PFASDataReviewView
    found = []
    config, now = _config_mark(portal), time.time()
    brains = api.search({"portal_type": "Worksheet", "review_state": list(OPEN_STATES)},
                        "senaite_catalog_worksheet")
    for brain in brains:
        try:
            ws = api.get_object(brain)
            if api.get_review_status(ws) not in OPEN_STATES or retired.is_retired(ws):
                continue
            mark = _mark(ws, config)
            if unchanged(api.get_uid(ws), mark, now):
                continue
            review = PFASDataReviewView(ws, request)
            if review.has_run():
                dev = review.raise_unconfigured_deviation(ws)
                if dev and dev.get("dev_id"):
                    found.append(dev["dev_id"])
            _JUDGED[api.get_uid(ws)] = (mark, now)
        except Exception as exc:                            # noqa: BLE001
            logger.error("unconfigured-criteria deviation for %s: %s",
                         getattr(brain, "getId", u"?"), exc)
    return found


class PFASUnconfiguredDeviationView(object):

    def __init__(self, context, request):
        self.context, self.request = context, request

    def _refuse(self, status, error):
        self.request.response.setStatus(status)
        return json.dumps({"ok": False, "error": error})

    def __call__(self):
        from bika.lims import api
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.method != "POST":
            return self._refuse(405, u"POST only")
        try:
            body = json.loads(self.request.get("BODY") or u"{}")
            uid = body.get("worksheet_uid") or u""
        except (AttributeError, TypeError, ValueError):
            return self._refuse(400, u"not JSON")
        ws = api.get_object_by_uid(uid, default=None) if uid else None
        if ws is None or getattr(ws, "portal_type", u"") != "Worksheet":
            return self._refuse(404, u"no such worksheet")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)
        from senaite.pfas.browser.data_review import PFASDataReviewView
        dev = PFASDataReviewView(ws, self.request).raise_unconfigured_deviation(ws)
        return json.dumps({"ok": True, "dev_id": (dev or {}).get("dev_id") or u""})
