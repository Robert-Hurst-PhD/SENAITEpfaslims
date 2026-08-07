"""The facility QC dashboard must read the table each unit actually writes to.

ISO 17025 §6.4 makes environmental and equipment monitoring an independent
compliance obligation, reviewed by the QAO on its own cadence. The dashboard is
where that review happens, so a unit reporting green is a claim about
compliance.

Eye wash stations were grouped with the temperature sensors, so their status
came from `latest_reading()` — which queries `temperature_readings`, a table an
eye wash station never writes to. Every station therefore reported `no_data`
forever, while `save_eyewash_log` was computing and storing a `passed` verdict
(the station runs AND its water is tepid) that nothing read.

Two things this file also pins, both found by writing it:

  * `log_time` is only HH:MM, so two entries in the same minute TIE. Without an
    `id DESC` tiebreak SQLite returns the first by rowid — so re-testing a
    station after a failure reported the earlier PASSING entry as current. The
    first version of the fix had exactly that bug and this test caught it.
  * an unknown `unit_type` used to fall through to `status = "ok"`. A dashboard
    that cannot check something must not claim it passed.

Runs against a scratch database via `PFAS_FACILITY_QC_DB`; it never touches
`/data/qc/facility_monitoring.db`.
"""
import importlib.util
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "src", "senaite", "pfas", "facility_qc.py")


def _fresh_module():
    """A facility_qc bound to its own empty database.

    Loaded by path rather than imported: `senaite.pfas.__init__` pulls in
    zope.i18nmessageid, and DB_PATH is read at import time so the environment
    has to be set before the module object exists.
    """
    path = os.path.join(tempfile.mkdtemp(prefix="pfas_fac_"), "facility.db")
    os.environ["PFAS_FACILITY_QC_DB"] = path
    spec = importlib.util.spec_from_file_location("pfas_facility_qc_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DB_PATH == path, module.DB_PATH
    module.ensure_schema()
    return module


def _status(fq, name):
    rows = {r["name"]: r["status"] for r in fq.dashboard_summary()}
    return rows[name]


def _unit(fq, unit_type, name):
    return fq.save_unit({"unit_type": unit_type, "name": name,
                         "location": "Lab", "serial_number": "",
                         "sensor_id": ""})


def test_an_eyewash_station_is_judged_on_its_own_log():
    fq = _fresh_module()
    _unit(fq, "eyewash", "EW")
    assert _status(fq, "EW") == "no_data", "never checked -> no_data"

    fq.save_eyewash_log(fq.list_units()[0]["id"], "KP", working=True,
                        temperature=20.0)
    assert _status(fq, "EW") == "ok", "runs, water tepid, checked today"


def test_a_failing_station_is_reported_failing():
    fq = _fresh_module()
    _unit(fq, "eyewash", "EW")
    uid = fq.list_units()[0]["id"]

    fq.save_eyewash_log(uid, "KP", working=True, temperature=40.0)
    assert _status(fq, "EW") == "out_of_range", "water far too hot"

    fq.save_eyewash_log(uid, "KP", working=False, temperature=20.0)
    assert _status(fq, "EW") == "out_of_range", "station does not run"


def test_the_latest_entry_wins_even_within_the_same_minute():
    """`log_time` is HH:MM. Re-testing a station after a failed check writes a
    second entry in the same minute; without a deterministic tiebreak the
    dashboard showed the FIRST one."""
    fq = _fresh_module()
    _unit(fq, "eyewash", "EW")
    uid = fq.list_units()[0]["id"]
    stamp = {"log_date": "2026-08-07", "log_time": "09:15"}

    fq.save_eyewash_log(uid, "KP", working=True, temperature=20.0, **stamp)
    fq.save_eyewash_log(uid, "KP", working=False, temperature=20.0, **stamp)
    assert _status(fq, "EW") == "out_of_range", (
        "a failure logged in the same minute as an earlier pass must win")

    fq.save_eyewash_log(uid, "KP", working=True, temperature=20.0, **stamp)
    assert _status(fq, "EW") == "ok", "and the repair after it must win too"


def test_an_old_but_passing_check_is_pending_not_ok_and_not_overdue():
    """§6.4 puts eye wash on its own cadence, so an older entry is flagged for
    review rather than measured against the 25-hour sensor window."""
    fq = _fresh_module()
    _unit(fq, "eyewash", "EW")
    fq.save_eyewash_log(fq.list_units()[0]["id"], "KP", working=True,
                        temperature=20.0, log_date="2026-01-02")
    assert _status(fq, "EW") == "pending"


def test_an_eyewash_never_consults_the_temperature_table():
    """The defect itself. A temperature reading filed against an eye wash unit
    must not make it green."""
    fq = _fresh_module()
    _unit(fq, "eyewash", "EW")
    uid = fq.list_units()[0]["id"]
    with fq._connect() as conn:
        conn.execute(
            "INSERT INTO temperature_readings "
            "(unit_id, sensor_id, ts, temperature, in_range, source, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, "s1", fq._now(), 4.0, 1, "manual", fq._now()))
    assert _status(fq, "EW") == "no_data", (
        "the dashboard is reading temperature_readings for an eye wash again")


def test_an_unknown_unit_type_does_not_claim_compliance():
    """Every type in UNIT_TYPES is handled, so this branch means someone added
    one without a check. Green would hide precisely that."""
    fq = _fresh_module()
    _unit(fq, "fume_hood", "Hood 1")       # not in UNIT_TYPES
    assert _status(fq, "Hood 1") == "no_data"


def test_every_declared_unit_type_has_a_real_check():
    """A type that reaches the fallback is not being monitored."""
    fq = _fresh_module()
    for unit_type, label in fq.UNIT_TYPES:
        _unit(fq, unit_type, "U-%s" % unit_type)
    statuses = {r["unit_type"]: r["status"] for r in fq.dashboard_summary()}
    # with no data at all, every type must say so -- never "ok"
    green = sorted(t for t, s in statuses.items() if s == "ok")
    assert not green, (
        "these unit types report OK with no data recorded at all: %s" % green)


def test_the_dashboard_statuses_all_render():
    """A status the view cannot label shows the raw string to a QAO."""
    view = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "facility_qc.py")
    with open(view) as fh:
        body = fh.read()
    for status in ("ok", "out_of_range", "overdue", "pending", "no_data"):
        assert '"%s"' % status in body, (
            "%s has no label/class in the dashboard view" % status)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
