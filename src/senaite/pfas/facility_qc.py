# -*- coding: utf-8 -*-
"""Facility-wide daily QC data store (ISO 17025).

All records live in a single SQLite database shared between the Zope
browser process and the Raspberry Pi sensor reader.

Tables
------
facility_units          — configurable registry of physical units
temperature_readings    — time-series readings from RPi sensors
temperature_studies     — quarterly NIST qualification study headers
temperature_study_points — individual time-point readings within a study
balance_verifications   — per-session balance check headers
balance_verification_points — per-weight readings within a session
water_qc_logs           — Type 1 water daily entries
waste_logs              — SAA waste container entries
eyewash_logs            — eye wash station verification entries
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime

logger = logging.getLogger("senaite.pfas.facility_qc")

DB_PATH = os.environ.get("PFAS_FACILITY_QC_DB", "/data/qc/facility_monitoring.db")

UNIT_TYPES = [
    ("refrigerator",       "Refrigerator"),
    ("freezer",            "Freezer"),
    ("balance_analytical", "Balance — Analytical"),
    ("balance_prep",       "Balance — Preparatory"),
    ("eyewash",            "Eye Wash Station"),
    ("water_system",       "Type 1 Water System"),
    ("room_sensor",        "Room Sensor"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Lab-wide facility defaults.
#
# These are LABORATORY VALUES, not code constants: a lab with a different
# weight set, a different water specification or a local eyewash requirement
# has to be able to change them once, not retype them on every unit it creates.
# The tables below are SEEDS. get_facility_defaults() merges the lab's saved
# overrides over them, and every consumer reads through that rather than
# importing the table directly.
#
# Facility QC is an independent compliance obligation (§10) reviewed by the QAO
# on its own cadence, so these do not gate batch release — but they do decide
# whether a balance or a water system passes, which is a lab decision.
# ─────────────────────────────────────────────────────────────────────────────

FACILITY_DEFAULTS_KEY = "senaite.pfas.facility_defaults"

# Default balance weight points per type: [nominal_g, label, tolerance_g]
BALANCE_DEFAULTS = {
    "balance_analytical": [
        [0.010, "10 mg",  0.0001],
        [1.0,   "1 g",    0.001],
        [10.0,  "10 g",   0.005],
        [100.0, "100 g",  0.050],
    ],
    "balance_prep": [
        [1.0,   "1 g",    0.001],
        [10.0,  "10 g",   0.010],
        [100.0, "100 g",  0.100],
        [200.0, "200 g",  0.200],
        [500.0, "500 g",  0.500],
    ],
}

EYEWASH_TEMP_MIN = 15.0
EYEWASH_TEMP_MAX = 25.0

WATER_QC_DEFAULTS = {
    "conductivity_max": 1.0,   # μS/cm
    "toc_max": 500.0,           # ppb
}

# Fallbacks used when a unit records none of its own.
STUDY_TOLERANCE_DEFAULT = 1.0   # °C, temperature-mapping study
BALANCE_TOLERANCE_DEFAULT = 0.001  # g, when a weight point carries no tolerance


def _defaults_seed():
    return {
        "balance_points": dict(
            (k, [list(p) for p in v]) for k, v in BALANCE_DEFAULTS.items()),
        "eyewash_temp_min": EYEWASH_TEMP_MIN,
        "eyewash_temp_max": EYEWASH_TEMP_MAX,
        "water_conductivity_max": WATER_QC_DEFAULTS["conductivity_max"],
        "water_toc_max": WATER_QC_DEFAULTS["toc_max"],
        "study_tolerance": STUDY_TOLERANCE_DEFAULT,
        "balance_tolerance": BALANCE_TOLERANCE_DEFAULT,
    }


def get_facility_defaults(portal=None):
    """Lab-wide facility defaults: saved values over the seed.

    `portal` is optional so the pure-SQLite layer keeps working headlessly
    (the worker and the migration scripts have no portal); without one the seed
    is returned, which is the same behaviour as before this was configurable.
    """
    out = _defaults_seed()
    if portal is None:
        return out
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(portal).get(FACILITY_DEFAULTS_KEY)
    except Exception:                                       # noqa: BLE001
        return out
    if not raw:
        return out
    try:
        saved = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("facility defaults unreadable; using seed values")
        return out
    for key, value in (saved or {}).items():
        if key in out and value not in (None, "", {}, []):
            out[key] = value
    return out


def save_facility_defaults(portal, data):
    """Store only what differs from the seed, so seed corrections still reach a
    lab that never overrode a given value."""
    seed = _defaults_seed()
    trimmed = {}
    for key, value in (data or {}).items():
        if key not in seed or value in (None, ""):
            continue
        if value != seed[key]:
            trimmed[key] = value
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[FACILITY_DEFAULTS_KEY] = json.dumps(trimmed)
    return trimmed

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facility_units (
    id           TEXT PRIMARY KEY,
    unit_type    TEXT NOT NULL,
    name         TEXT NOT NULL,
    location     TEXT,
    serial_number TEXT,
    sensor_id    TEXT UNIQUE,
    temp_min     REAL,
    temp_max     REAL,
    humidity_min REAL,
    humidity_max REAL,
    study_tolerance REAL DEFAULT 1.0,
    weight_points_json TEXT,
    extra_config_json  TEXT,
    active       INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS temperature_readings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      TEXT NOT NULL,
    sensor_id    TEXT NOT NULL,
    ts           TEXT NOT NULL,
    temperature  REAL,
    humidity     REAL,
    in_range     INTEGER DEFAULT 1,
    source       TEXT DEFAULT 'sensor',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tr_unit_ts ON temperature_readings(unit_id, ts);

CREATE TABLE IF NOT EXISTS temperature_studies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      TEXT NOT NULL,
    study_date   TEXT NOT NULL,
    operator     TEXT NOT NULL,
    nist_serial  TEXT NOT NULL,
    nist_cert_date TEXT,
    tolerance    REAL DEFAULT 1.0,
    status       TEXT DEFAULT 'pending',
    notes        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS temperature_study_points (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id     INTEGER NOT NULL,
    time_point   INTEGER NOT NULL,
    recorded_at  TEXT,
    sensor_reading REAL,
    nist_reading   REAL,
    deviation      REAL,
    passed         INTEGER
);

CREATE TABLE IF NOT EXISTS balance_verifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      TEXT NOT NULL,
    verified_date TEXT NOT NULL,
    operator     TEXT NOT NULL,
    passed       INTEGER DEFAULT 1,
    notes        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS balance_verification_points (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL,
    nominal_g      REAL NOT NULL,
    label          TEXT,
    actual_g       REAL,
    deviation_g    REAL,
    tolerance_g    REAL,
    passed         INTEGER
);

CREATE TABLE IF NOT EXISTS water_qc_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date        TEXT NOT NULL,
    log_time        TEXT NOT NULL,
    operator        TEXT NOT NULL,
    conductivity    REAL,
    toc             REAL,
    conductivity_max REAL,
    toc_max         REAL,
    passed          INTEGER DEFAULT 1,
    notes           TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS waste_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      TEXT NOT NULL,
    log_date     TEXT NOT NULL,
    log_time     TEXT NOT NULL,
    operator     TEXT NOT NULL,
    condition    TEXT NOT NULL,
    notes        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eyewash_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      TEXT NOT NULL,
    log_date     TEXT NOT NULL,
    log_time     TEXT NOT NULL,
    operator     TEXT NOT NULL,
    working      INTEGER DEFAULT 1,
    temperature  REAL,
    temp_min     REAL DEFAULT 15.0,
    temp_max     REAL DEFAULT 25.0,
    passed       INTEGER DEFAULT 1,
    notes        TEXT,
    created_at   TEXT NOT NULL
);
"""


def _connect():
    dir_ = os.path.dirname(DB_PATH)
    if dir_ and not os.path.exists(dir_):
        os.makedirs(dir_)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ── Unit registry ─────────────────────────────────────────────────────────────

def list_units(active_only=True):
    ensure_schema()
    with _connect() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM facility_units WHERE active=1 ORDER BY unit_type, name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM facility_units ORDER BY unit_type, name"
            ).fetchall()
    return [dict(r) for r in rows]


def get_unit(unit_id):
    ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM facility_units WHERE id=?", (unit_id,)
        ).fetchone()
    return dict(row) if row else None


def get_unit_by_sensor(sensor_id):
    ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM facility_units WHERE sensor_id=? AND active=1",
            (sensor_id,)
        ).fetchone()
    return dict(row) if row else None


def save_unit(data):
    """Insert or update a facility unit. Returns the unit id."""
    ensure_schema()
    uid = data.get("id") or str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM facility_units WHERE id=?", (uid,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE facility_units SET
                    unit_type=?, name=?, location=?, serial_number=?,
                    sensor_id=?, temp_min=?, temp_max=?,
                    humidity_min=?, humidity_max=?, study_tolerance=?,
                    weight_points_json=?, extra_config_json=?, active=?
                WHERE id=?
            """, (
                data.get("unit_type"), data.get("name"), data.get("location"),
                data.get("serial_number"), data.get("sensor_id") or None,
                _f(data.get("temp_min")), _f(data.get("temp_max")),
                _f(data.get("humidity_min")), _f(data.get("humidity_max")),
                _f(data.get("study_tolerance", STUDY_TOLERANCE_DEFAULT)),
                data.get("weight_points_json"), data.get("extra_config_json"),
                1 if data.get("active", True) else 0,
                uid,
            ))
        else:
            conn.execute("""
                INSERT INTO facility_units
                (id, unit_type, name, location, serial_number, sensor_id,
                 temp_min, temp_max, humidity_min, humidity_max, study_tolerance,
                 weight_points_json, extra_config_json, active, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid, data.get("unit_type"), data.get("name"),
                data.get("location"), data.get("serial_number"),
                data.get("sensor_id") or None,
                _f(data.get("temp_min")), _f(data.get("temp_max")),
                _f(data.get("humidity_min")), _f(data.get("humidity_max")),
                _f(data.get("study_tolerance", STUDY_TOLERANCE_DEFAULT)),
                data.get("weight_points_json"), data.get("extra_config_json"),
                1 if data.get("active", True) else 0,
                now,
            ))
    return uid


def delete_unit(unit_id):
    ensure_schema()
    with _connect() as conn:
        conn.execute(
            "UPDATE facility_units SET active=0 WHERE id=?", (unit_id,)
        )


# ── Temperature readings ──────────────────────────────────────────────────────

def record_temperature(unit_id, sensor_id, temperature, humidity=None,
                        ts=None, source="sensor"):
    ensure_schema()
    unit = get_unit(unit_id)
    in_range = 1
    if unit and temperature is not None:
        lo = unit.get("temp_min")
        hi = unit.get("temp_max")
        if lo is not None and temperature < lo:
            in_range = 0
        if hi is not None and temperature > hi:
            in_range = 0
    if humidity is not None and unit:
        hlo = unit.get("humidity_min")
        hhi = unit.get("humidity_max")
        if hlo is not None and humidity < hlo:
            in_range = 0
        if hhi is not None and humidity > hhi:
            in_range = 0
    ts = ts or _now()
    now = _now()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO temperature_readings
            (unit_id, sensor_id, ts, temperature, humidity, in_range, source, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (unit_id, sensor_id, ts, temperature, humidity, in_range, source, now))
    return in_range


def get_temperature_readings(unit_id, days=7):
    ensure_schema()
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM temperature_readings
            WHERE unit_id=? AND ts >= ?
            ORDER BY ts ASC
        """, (unit_id, cutoff)).fetchall()
    return [dict(r) for r in rows]


def latest_reading(unit_id):
    ensure_schema()
    with _connect() as conn:
        row = conn.execute("""
            SELECT * FROM temperature_readings
            WHERE unit_id=?
            ORDER BY ts DESC LIMIT 1
        """, (unit_id,)).fetchone()
    return dict(row) if row else None


# ── Temperature studies ───────────────────────────────────────────────────────

def list_studies(unit_id):
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM temperature_studies WHERE unit_id=? ORDER BY study_date DESC
        """, (unit_id,)).fetchall()
    return [dict(r) for r in rows]


def get_study(study_id):
    ensure_schema()
    with _connect() as conn:
        study = conn.execute(
            "SELECT * FROM temperature_studies WHERE id=?", (study_id,)
        ).fetchone()
        if not study:
            return None
        points = conn.execute(
            "SELECT * FROM temperature_study_points WHERE study_id=? ORDER BY time_point",
            (study_id,)
        ).fetchall()
    return {"study": dict(study), "points": [dict(p) for p in points]}


def create_study(unit_id, operator, nist_serial, nist_cert_date=None,
                 study_date=None, tolerance=1.0, notes=None):
    ensure_schema()
    now = _now()
    study_date = study_date or now[:10]
    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO temperature_studies
            (unit_id, study_date, operator, nist_serial, nist_cert_date,
             tolerance, status, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (unit_id, study_date, operator, nist_serial, nist_cert_date,
              tolerance, "pending", notes, now))
        study_id = cur.lastrowid
        for i in range(1, 6):
            conn.execute("""
                INSERT INTO temperature_study_points (study_id, time_point)
                VALUES (?,?)
            """, (study_id, i))
    return study_id


def save_study_point(study_id, time_point, sensor_reading, nist_reading,
                     recorded_at=None):
    ensure_schema()
    recorded_at = recorded_at or _now()
    deviation = None
    passed = None
    if sensor_reading is not None and nist_reading is not None:
        deviation = round(sensor_reading - nist_reading, 4)
    with _connect() as conn:
        study = conn.execute(
            "SELECT tolerance FROM temperature_studies WHERE id=?", (study_id,)
        ).fetchone()
        if study and deviation is not None:
            passed = 1 if abs(deviation) <= float(study["tolerance"]) else 0
        conn.execute("""
            UPDATE temperature_study_points
            SET sensor_reading=?, nist_reading=?, deviation=?, passed=?, recorded_at=?
            WHERE study_id=? AND time_point=?
        """, (sensor_reading, nist_reading, deviation, passed, recorded_at,
              study_id, time_point))
        _refresh_study_status(conn, study_id)


def _refresh_study_status(conn, study_id):
    pts = conn.execute(
        "SELECT passed FROM temperature_study_points WHERE study_id=?",
        (study_id,)
    ).fetchall()
    filled = [p for p in pts if p["passed"] is not None]
    if len(filled) < 5:
        status = "pending"
    elif all(p["passed"] == 1 for p in filled):
        status = "pass"
    else:
        status = "fail"
    conn.execute(
        "UPDATE temperature_studies SET status=? WHERE id=?",
        (status, study_id)
    )


# ── Balance verifications ─────────────────────────────────────────────────────

def save_balance_verification(unit_id, operator, verified_date, points, notes=None):
    """points: list of {nominal_g, label, actual_g, tolerance_g}"""
    ensure_schema()
    now = _now()
    all_passed = True
    processed = []
    for p in points:
        actual = _f(p.get("actual_g"))
        nominal = float(p["nominal_g"])
        # A weight point with no tolerance falls back to the lab's configured
        # default rather than a literal, so one place sets it.
        tol = float(p.get("tolerance_g") or BALANCE_TOLERANCE_DEFAULT)
        dev = round(actual - nominal, 6) if actual is not None else None
        passed = (1 if dev is not None and abs(dev) <= tol else 0) if dev is not None else None
        if passed == 0:
            all_passed = False
        processed.append({
            "nominal_g": nominal,
            "label": p.get("label", ""),
            "actual_g": actual,
            "deviation_g": dev,
            "tolerance_g": tol,
            "passed": passed,
        })
    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO balance_verifications
            (unit_id, verified_date, operator, passed, notes, created_at)
            VALUES (?,?,?,?,?,?)
        """, (unit_id, verified_date, operator, 1 if all_passed else 0, notes, now))
        vid = cur.lastrowid
        for p in processed:
            conn.execute("""
                INSERT INTO balance_verification_points
                (verification_id, nominal_g, label, actual_g, deviation_g, tolerance_g, passed)
                VALUES (?,?,?,?,?,?,?)
            """, (vid, p["nominal_g"], p["label"], p["actual_g"],
                  p["deviation_g"], p["tolerance_g"], p["passed"]))
    return vid


def list_balance_verifications(unit_id, limit=30):
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM balance_verifications WHERE unit_id=?
            ORDER BY verified_date DESC LIMIT ?
        """, (unit_id, limit)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            pts = conn.execute("""
                SELECT * FROM balance_verification_points WHERE verification_id=?
                ORDER BY nominal_g
            """, (r["id"],)).fetchall()
            d["points"] = [dict(p) for p in pts]
            result.append(d)
    return result


# ── Water QC ──────────────────────────────────────────────────────────────────

def save_water_qc(operator, conductivity, toc, log_date=None, log_time=None,
                  conductivity_max=None, toc_max=None, notes=None):
    ensure_schema()
    now = _now()
    log_date = log_date or now[:10]
    log_time = log_time or now[11:16]
    c_max = conductivity_max if conductivity_max is not None else WATER_QC_DEFAULTS["conductivity_max"]
    t_max = toc_max if toc_max is not None else WATER_QC_DEFAULTS["toc_max"]
    passed = 1
    if conductivity is not None and conductivity > c_max:
        passed = 0
    if toc is not None and toc > t_max:
        passed = 0
    with _connect() as conn:
        conn.execute("""
            INSERT INTO water_qc_logs
            (log_date, log_time, operator, conductivity, toc,
             conductivity_max, toc_max, passed, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (log_date, log_time, operator, conductivity, toc,
              c_max, t_max, passed, notes, now))
    return passed


def list_water_qc(limit=30):
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM water_qc_logs ORDER BY log_date DESC, log_time DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Waste logs ────────────────────────────────────────────────────────────────

def save_waste_log(unit_id, operator, condition, log_date=None,
                   log_time=None, notes=None):
    ensure_schema()
    now = _now()
    log_date = log_date or now[:10]
    log_time = log_time or now[11:16]
    with _connect() as conn:
        conn.execute("""
            INSERT INTO waste_logs
            (unit_id, log_date, log_time, operator, condition, notes, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (unit_id, log_date, log_time, operator, condition, notes, now))


def list_waste_logs(unit_id=None, limit=30):
    ensure_schema()
    with _connect() as conn:
        if unit_id:
            rows = conn.execute("""
                SELECT w.*, u.name as unit_name FROM waste_logs w
                LEFT JOIN facility_units u ON u.id=w.unit_id
                WHERE w.unit_id=? ORDER BY w.log_date DESC, w.log_time DESC LIMIT ?
            """, (unit_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT w.*, u.name as unit_name FROM waste_logs w
                LEFT JOIN facility_units u ON u.id=w.unit_id
                ORDER BY w.log_date DESC, w.log_time DESC LIMIT ?
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Eye wash logs ─────────────────────────────────────────────────────────────

def save_eyewash_log(unit_id, operator, working, temperature=None,
                     log_date=None, log_time=None,
                     temp_min=None, temp_max=None, notes=None):
    ensure_schema()
    now = _now()
    log_date = log_date or now[:10]
    log_time = log_time or now[11:16]
    t_min = temp_min if temp_min is not None else EYEWASH_TEMP_MIN
    t_max = temp_max if temp_max is not None else EYEWASH_TEMP_MAX
    passed = 1 if working else 0
    if temperature is not None:
        if temperature < t_min or temperature > t_max:
            passed = 0
    with _connect() as conn:
        conn.execute("""
            INSERT INTO eyewash_logs
            (unit_id, log_date, log_time, operator, working, temperature,
             temp_min, temp_max, passed, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (unit_id, log_date, log_time, operator, 1 if working else 0,
              temperature, t_min, t_max, passed, notes, now))
    return passed


def list_eyewash_logs(unit_id=None, limit=30):
    ensure_schema()
    with _connect() as conn:
        if unit_id:
            rows = conn.execute("""
                SELECT e.*, u.name as unit_name FROM eyewash_logs e
                LEFT JOIN facility_units u ON u.id=e.unit_id
                WHERE e.unit_id=? ORDER BY e.log_date DESC, e.log_time DESC LIMIT ?
            """, (unit_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT e.*, u.name as unit_name FROM eyewash_logs e
                LEFT JOIN facility_units u ON u.id=e.unit_id
                ORDER BY e.log_date DESC, e.log_time DESC LIMIT ?
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Dashboard summary ─────────────────────────────────────────────────────────

def dashboard_summary():
    """Return one status row per unit for the daily checklist dashboard."""
    ensure_schema()
    from datetime import timedelta
    units = list_units(active_only=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    overdue_hours = 25  # flag if no reading in 25 hours
    cutoff_ts = (datetime.utcnow() - timedelta(hours=overdue_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    result = []
    for u in units:
        row = dict(u)
        ut = u["unit_type"]
        if ut in ("refrigerator", "freezer", "room_sensor"):
            reading = latest_reading(u["id"])
            row["last_reading"] = reading
            if not reading:
                row["status"] = "no_data"
            elif reading["ts"] < cutoff_ts:
                row["status"] = "overdue"
            elif not reading["in_range"]:
                row["status"] = "out_of_range"
            else:
                row["status"] = "ok"
        elif ut == "eyewash":
            # Eye wash stations are logged in `eyewash_logs`, NOT in
            # `temperature_readings`. Until 2026-08-07 they were grouped with
            # the temperature sensors above, so `latest_reading()` queried a
            # table an eye wash station never writes to and every station
            # reported `no_data` forever -- while `save_eyewash_log` was
            # computing and storing a `passed` verdict (the station runs AND
            # its water is tepid, ISO 17025 §6.3) that nothing ever read.
            #
            # Periodic, not daily: §6.4 puts eye wash on its own cadence, so an
            # older entry is reported as `pending` for review rather than
            # `overdue` against the 25-hour sensor window.
            with _connect() as conn:
                # `id DESC` is a REQUIRED tiebreak, not decoration: log_time is
                # only HH:MM, so two entries in the same minute tie and SQLite
                # returns them in rowid order -- i.e. the FIRST one. Re-testing
                # a station after a failed check would then have reported the
                # earlier passing entry as current.
                ew = conn.execute("""
                    SELECT * FROM eyewash_logs
                    WHERE unit_id=?
                    ORDER BY log_date DESC, log_time DESC, id DESC
                    LIMIT 1
                """, (u["id"],)).fetchone()
            row["last_eyewash"] = dict(ew) if ew else None
            if not ew:
                row["status"] = "no_data"
            elif not ew["passed"]:
                row["status"] = "out_of_range"
            elif ew["log_date"] < today:
                row["status"] = "pending"
            else:
                row["status"] = "ok"
        elif ut in ("balance_analytical", "balance_prep"):
            with _connect() as conn:
                bv = conn.execute("""
                    SELECT * FROM balance_verifications
                    WHERE unit_id=? AND verified_date=?
                    ORDER BY created_at DESC LIMIT 1
                """, (u["id"], today)).fetchone()
            row["last_balance"] = dict(bv) if bv else None
            if not bv:
                row["status"] = "pending"
            elif bv["passed"]:
                row["status"] = "ok"
            else:
                row["status"] = "out_of_range"
        elif ut == "water_system":
            with _connect() as conn:
                wq = conn.execute("""
                    SELECT * FROM water_qc_logs WHERE log_date=?
                    ORDER BY log_time DESC LIMIT 1
                """, (today,)).fetchone()
            row["last_water"] = dict(wq) if wq else None
            if not wq:
                row["status"] = "pending"
            elif wq["passed"]:
                row["status"] = "ok"
            else:
                row["status"] = "out_of_range"
        else:
            # A unit type this dashboard does not know how to check must not
            # claim compliance. Every type in UNIT_TYPES is handled above, so
            # reaching here means one was added without a check -- reporting it
            # green would hide exactly that.
            logger.warning(
                "facility QC: unit %s has type %r with no status check; "
                "reporting no_data rather than OK", u.get("id"), ut)
            row["status"] = "no_data"
        result.append(row)
    return result


# ── API key helpers ───────────────────────────────────────────────────────────

def get_api_key(portal):
    """Read the sensor ingest API key from portal annotations."""
    try:
        from zope.annotation.interfaces import IAnnotations
        ann = IAnnotations(portal)
        return ann.get("senaite.pfas.facility_qc.api_key", "")
    except Exception:
        return ""


def set_api_key(portal, key):
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    ann["senaite.pfas.facility_qc.api_key"] = key


def _f(v):
    """Convert to float or return None."""
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None
