# -*- coding: utf-8 -*-
"""When a result was analysed: one answer for every document that prints it
(the certificate, the QC Review, the EDD).

A result is analysed when its injection was acquired on the instrument, as
the instrument stamps it (on the laboratory's clock). The worker logs that
time with each result it pushes (result_pushes.acquired_at) and with each
injection row it stores (injection_results.acquired_at); a pushed result
whose own row carries no time takes its injection's. A result with no
acquisition time anywhere (typed by hand, or a dilution's retest, which
keeps its own instant) is analysed when SENAITE captured it. Nothing else
stands in: a run's date is not an injection's acquisition time.

    acquired_by_uid(uids=None)   {analysis uid: "YYYY-MM-DDTHH:MM:SS"}
    acquisition_days(batch_id)   the days a worksheet's injections were acquired
    shown(acquired, captured, fmt)   the text a document prints
    refusal(undated)                 why a certificate is refused for results with no date
    wall(acquired, captured)         the instant shown() prints, on the laboratory's clock
    before_receipt(analysed, received)  analysed before the sample was received
    early_refusal(names, received)   why a certificate is refused for those results

Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import logging
import os
import sqlite3

logger = logging.getLogger("senaite.pfas.analysed_at")

_CHUNK = 500


def _connect(path):
    """A connection to the QC store, or None when it does not exist
    (opening a missing database would create it: a read writes nothing)."""
    from senaite.pfas.qc import store
    path = path or store.DEFAULT_DB_PATH
    if not os.path.exists(path):
        return None
    return sqlite3.connect(path)


def _pushes(conn, uids):
    """{uid: (acquired_at, batch_id, injection)} from the push log, the latest
    good push of each result; its time is the latest push that logged one."""
    sql = ("SELECT analysis_uid, acquired_at, batch_id, injection FROM result_pushes "
           "WHERE ok=1")
    rows = []
    if uids is None:
        rows = conn.execute(sql + " ORDER BY rowid").fetchall()
    else:
        uids = [u for u in uids if u]
        for i in range(0, len(uids), _CHUNK):
            part = uids[i:i + _CHUNK]
            rows += conn.execute(sql + " AND analysis_uid IN (%s) ORDER BY rowid"
                                 % ",".join("?" * len(part)), part).fetchall()
    out = {}
    for uid, at, batch_id, injection in rows:
        had = out.get(uid)
        # the latest push names the injection; a time logged earlier stays
        # when a later push logged none
        out[uid] = ((at or "") or (had[0] if had else ""), batch_id or "", injection or "")
    return out


def _injection_times(conn, keys):
    """{(batch_id, injection): acquisition time} for the injections `keys`
    name, by the injection's own name only: never another injection of the
    same sample (a dilution, a spike), whose time is its own."""
    out = {}
    for batch_id in sorted(set(b for b, _i in keys)):
        names = set(i for b, i in keys if b == batch_id)
        for name, at in conn.execute(
                "SELECT injection_name, MAX(acquired_at) FROM injection_results "
                "WHERE batch_id=? AND acquired_at != '' GROUP BY injection_name",
                (batch_id,)):
            if name in names:
                out[(batch_id, name)] = at
    return out


def acquired_by_uid(uids=None, path=None):
    """{analysis uid: acquisition time} for every logged result, or those of
    `uids`: the time the push log carries, else the time its injection's
    rows carry. An unreadable store is logged and reads as no acquisition
    times, so the capture date stands in."""
    out = {}
    try:
        conn = _connect(path)
        if conn is None:
            return out
        try:
            pushes = _pushes(conn, uids)
            missing = set((b, i) for at, b, i in pushes.values() if not at and b and i)
            times = _injection_times(conn, missing) if missing else {}
            for uid, (at, batch_id, injection) in pushes.items():
                at = at or times.get((batch_id, injection)) or ""
                if at:
                    out[uid] = at
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("acquisition times unreadable: %s", exc)
    return out


def acquisition_days(batch_id, path=None):
    """The days ("YYYY-MM-DD", in order) a worksheet's injections were
    acquired, from the same logged times; [] when none is logged."""
    if not batch_id:
        return []
    days = set()
    try:
        conn = _connect(path)
        if conn is None:
            return []
        try:
            for (at,) in conn.execute(
                    "SELECT DISTINCT substr(acquired_at, 1, 10) FROM injection_results "
                    "WHERE batch_id=? AND acquired_at != ''", (batch_id,)):
                days.add(at)
            for (at,) in conn.execute(
                    "SELECT DISTINCT substr(acquired_at, 1, 10) FROM result_pushes "
                    "WHERE batch_id=? AND ok=1 AND acquired_at != ''", (batch_id,)):
                days.add(at)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("acquisition days unreadable: %s", exc)
    return sorted(d for d in days if d)


def shown(acquired, captured, fmt):
    """"YYYY-MM-DD HH:MM" for one result: its logged acquisition time as
    stored (already the laboratory's clock), else fmt(captured), the
    capture date as the document shows an instant; "" with neither."""
    text = (acquired or "").strip()
    if len(text) >= 16 and text[4] == "-" and text[10] in "T ":
        return "%s %s" % (text[:10], text[11:16])
    return fmt(captured) if captured else ""


def wall(acquired, captured):
    """The analysis instant `shown` prints, as a naive datetime on the
    laboratory's clock to the minute: the logged acquisition time (already
    the laboratory's clock), else the capture date (an instant, converted
    to the laboratory's zone); None with neither."""
    from senaite.pfas import lab_time
    when = None
    text = (acquired or "").strip()
    if len(text) >= 16 and text[4] == "-" and text[10] in "T ":
        when = lab_time.to_wall(text, "lab")
    if when is None and captured:
        when = lab_time.to_wall(captured, "utc")
    return when.replace(second=0, microsecond=0) if when is not None else None


def before_receipt(analysed, received):
    """True when `analysed` (wall()) is earlier than the sample's receipt
    (an instant) on the laboratory's clock, both to the minute as the
    certificate prints them; a receipt with no time counts from the start of
    its day. False when either is missing."""
    from senaite.pfas import lab_time
    if analysed is None or not received:
        return False
    got = lab_time.to_wall(received, "utc")
    if got is None:
        return False
    return analysed < got.replace(second=0, microsecond=0)


def early_refusal(names, received):
    """The refusal text for a sample with results analysed before it was
    received (`received` as the certificate prints it): names the analytes
    (the caller names the sample). None when there are none."""
    names = [n for n in (names or []) if n]
    if not names:
        return None
    return ("analysed before the sample was received (%s): %s. Correct the receipt "
            "date or the analysis date before the certificate is issued."
            % (received or "no receipt date", ", ".join(names)))


def refusal(undated):
    """The refusal text for a sample whose reported results have no analysis
    date: names the analytes and says where the date comes from (the caller
    names the sample). None when every reported result is dated."""
    names = [n for n in (undated or []) if n]
    if not names:
        return None
    return ("no analysis date for %s. A result's date is its injection's "
            "acquisition time, logged when the worker pushes it, or else the "
            "date it was captured in SENAITE; capture or re-push these results."
            % ", ".join(names))
