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
import re
import sqlite3
import uuid
from datetime import datetime

logger = logging.getLogger("senaite.pfas.facility_qc")

from senaite.pfas import equipment_types as _et
from senaite.pfas import temp_calibration as tc

DB_PATH = os.environ.get("PFAS_FACILITY_QC_DB", "/data/qc/facility_monitoring.db")

UNIT_TYPES = [
    ("refrigerator",       "Refrigerator"),
    ("freezer",            "Freezer"),
    ("balance_analytical", "Analytical balance"),
    ("balance_prep",       "Top-loading balance"),
    ("eyewash",            "Eye Wash Station"),
    ("water_system",       "Type 1 Water System"),
    # A pipette is verified on a PERIOD, not daily: quarterly in house or by an
    # external provider. Its calibration record is what a result's volumetric
    # step traces to.
    ("pipette",            "Pipette"),
    ("room_sensor",        "Room Sensor"),
]

# Lab-wide facility defaults: LABORATORY VALUES, not code constants. The tables
# below are SEEDS; get_facility_defaults() merges the lab's saved overrides over
# them, and every consumer reads through it rather than importing a table.
# Facility QC is reviewed by the QAO on its own cadence and does not gate batch
# release, but these values decide whether a balance or a water system passes.

FACILITY_DEFAULTS_KEY = "senaite.pfas.facility_defaults"

# Default balance weight points per type: [nominal_g, label]. Acceptance is
# NOT per point: it is the balance type's tolerance, % of nominal (0.2 %; equipment_types.py), in grams.
BALANCE_DEFAULTS = {
    "balance_analytical": [
        [0.010, "10 mg"],
        [1.0,   "1 g"],
        [10.0,  "10 g"],
        [100.0, "100 g"],
    ],
    "balance_prep": [
        [1.0,   "1 g"],
        [10.0,  "10 g"],
        [100.0, "100 g"],
        [200.0, "200 g"],
        [500.0, "500 g"],
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


def _defaults_seed():
    return {
        "balance_points": dict(
            (k, [list(p) for p in v]) for k, v in BALANCE_DEFAULTS.items()),
        "eyewash_temp_min": EYEWASH_TEMP_MIN,
        "eyewash_temp_max": EYEWASH_TEMP_MAX,
        "water_conductivity_max": WATER_QC_DEFAULTS["conductivity_max"],
        "water_toc_max": WATER_QC_DEFAULTS["toc_max"],
        # the unit the water system reads: uS/cm (conductivity) or MOhm.cm
        # (resistivity = 1 / conductivity); judged in uS/cm either way
        "water_conductivity_unit": "uS/cm",
        "study_tolerance": STUDY_TOLERANCE_DEFAULT,
    }


def get_facility_defaults(portal=None):
    """Lab-wide facility defaults: saved values over the seed.

    `portal` is optional so the pure-SQLite layer keeps working headlessly
    (the worker and the migration scripts have no portal); without one the seed
    is returned.
    """
    out = _defaults_seed()
    if portal is None:
        return out
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(portal).get(FACILITY_DEFAULTS_KEY)
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
    from senaite.pfas import config_history
    config_history.track(portal, 'facility_defaults', "facility", lambda: get_facility_defaults(portal), label=u"Facility QC defaults")
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

-- ── Reference weight sets ────────────────────────────────────────────────────
-- A balance verification is only as good as the weights it was verified WITH, and
-- those are themselves calibrated by an external metrology laboratory. This is the
-- equipment analogue of a reagent's manufacturer CoA: the point where the chain
-- leaves this laboratory and becomes someone else's accredited measurement.
CREATE TABLE IF NOT EXISTS weight_sets (
    id            TEXT PRIMARY KEY,
    set_id        TEXT NOT NULL,          -- the lab's own identifier
    description   TEXT,
    weight_class  TEXT,                   -- ASTM Class 1, OIML E2, ...
    serial_number TEXT,
    -- external calibration, by a metrology laboratory
    cal_lab            TEXT,
    cal_lab_accreditation TEXT,           -- e.g. ISO/IEC 17025, scope number
    cal_cert_number    TEXT,
    cal_date           TEXT,              -- ISO 8601
    cal_due_date       TEXT,              -- ISO 8601
    nist_traceable     INTEGER DEFAULT 1,
    -- 0: the set is used without an external calibration (a recorded choice)
    calibration_required INTEGER DEFAULT 1,
    active        INTEGER DEFAULT 1,
    notes         TEXT,
    created_at    TEXT NOT NULL
);

-- ── Pipette calibration ──────────────────────────────────────────────────────
-- `kind` is 'internal' (a quarterly gravimetric check, done on a balance with a
-- weight set) or 'external' (a service provider's certificate). Both are
-- recorded; an internal check carries the balance and weight set it used, so a
-- pipette's provenance runs through them to the metrology lab as well.
CREATE TABLE IF NOT EXISTS pipette_calibrations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id       TEXT NOT NULL,          -- facility_units.id, unit_type=pipette
    kind          TEXT NOT NULL,          -- internal | external
    cal_date      TEXT NOT NULL,          -- ISO 8601
    due_date      TEXT,                   -- ISO 8601
    operator      TEXT,                   -- internal check
    provider      TEXT,                   -- external provider
    provider_accreditation TEXT,
    cert_number   TEXT,
    balance_unit_id TEXT,                 -- internal: the balance used
    weight_set_id TEXT,                   -- internal: the weight set used
    as_found_pct  REAL,                   -- worst as-found deviation
    tolerance_pct REAL,
    passed        INTEGER DEFAULT 1,
    notes         TEXT,
    created_at    TEXT NOT NULL
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

-- A study reading changed after it was recorded keeps what it was, who changed
-- it and when: a correction factor an auditor follows back must not
-- rest on a value that was silently overwritten.
CREATE TABLE IF NOT EXISTS temperature_study_point_changes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id       INTEGER NOT NULL,
    time_point     INTEGER NOT NULL,
    old_sensor     REAL,
    old_nist       REAL,
    old_recorded_at TEXT,
    old_entered_by TEXT,
    changed_by     TEXT,
    changed_at     TEXT NOT NULL
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


# A sqlite3.Row may only be subscripted with an int or a BYTE string. This module
# has `unicode_literals`, so every `row["col"]` in it passes a unicode key and
# raises
#
#     IndexError: Index must be int or string
#
# Convert to a dict before reading columns; do not reach for `b"col"`.


# Columns added to tables that already shipped. CREATE TABLE IF NOT EXISTS cannot
# add a column to an existing database, so these are applied explicitly and
# idempotently, without losing the rows already collected.
_ADDED_COLUMNS = [
    ("balance_verifications", "weight_set_id", "TEXT"),
    # a weight set used without an external calibration, as a recorded choice;
    # a set recorded before the choice existed still requires one
    ("weight_sets", "calibration_required", "INTEGER DEFAULT 1"),
    # the thermometer correction applied to a reading; the raw
    # probe value stays in `temperature`
    ("temperature_readings", "correction", "REAL"),
    # who entered each study reading
    ("temperature_study_points", "entered_by", "TEXT"),
    # the registered reference thermometer a study was read against
    ("temperature_studies", "reference_uid", "TEXT"),
    # the working temperature a study was done at (a multi-point
    # calibration: one study per working temperature, temp_calibration)
    ("temperature_studies", "study_temp", "REAL"),
    # the conductivity reading as entered, with its unit ("18.2 MOhm.cm");
    # `conductivity` is always uS/cm, the unit the limit is judged in
    ("water_qc_logs", "conductivity_entered", "TEXT"),
    # the water system a reading is of (its own limits); may be empty
    ("water_qc_logs", "unit_id", "TEXT"),
    # an in-house pipette calibration's weighings and what they gave
    # (pipette_cal.py), and the water temperature Z was read at
    ("pipette_calibrations", "measurements_json", "TEXT"),
    ("pipette_calibrations", "water_temp", "REAL"),
]


def ensure_schema():
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        for table, column, coltype in _ADDED_COLUMNS:
            have = set()
            try:
                for row in conn.execute("PRAGMA table_info(%s)" % table):
                    have.add(row[1])
            except sqlite3.Error:
                continue
            if column not in have:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                             % (table, column, coltype))


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _lab_now():
    """Now on the laboratory's clock, "YYYY-MM-DDTHH:MM:SS": what a date or
    time left blank defaults to. Stamps the system records (created_at, a
    reading's ts) stay _now(), UTC."""
    from senaite.pfas import lab_time
    return lab_time.now().replace(microsecond=0).isoformat()


_STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$")


def lab_clock():
    """A function giving a stored reading stamp, UTC "YYYY-MM-DDTHH:MM:SS",
    as a naive datetime on the laboratory's clock; None for any other value,
    which the caller reads through lab_time. The zone is resolved once, so a
    long series converts quickly. Only while lab_time.active()."""
    import pytz
    from senaite.pfas import lab_time
    tz, utc = pytz.timezone(lab_time.zone()), pytz.utc

    def wall(ts):
        if not isinstance(ts, lab_time.text_type) or not _STAMP.match(ts):
            return None
        try:
            stamp = datetime(int(ts[0:4]), int(ts[5:7]), int(ts[8:10]),
                             int(ts[11:13]), int(ts[14:16]), int(ts[17:19]))
        except ValueError:
            return None
        return utc.localize(stamp).astimezone(tz).replace(tzinfo=None)
    return wall



# ── The equipment registry ──────────────────────────────────────
# Inside SENAITE every unit IS a core Instrument (browser/equipment.py
# registers itself here at start-up): a unit's id is the instrument's UID, its
# name / serial / type come from the instrument, its PFAS settings from an
# annotation on it. The readings and verifications below stay in SQLite, keyed
# by that id. Without a provider (tests, scripts) the SQLite facility_units
# table answers, so the pure layer keeps working headlessly.
_PROVIDER = None


def set_unit_provider(provider):
    global _PROVIDER
    _PROVIDER = provider


def _provider():
    p = _PROVIDER
    return p if (p is not None and p.available()) else None


def list_units(active_only=True):
    if _provider():
        return _provider().list_units(active_only)
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
    if _provider():
        return _provider().get_unit(unit_id)
    ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM facility_units WHERE id=?", (unit_id,)
        ).fetchone()
    return dict(row) if row else None


def get_unit_by_sensor(sensor_id):
    if _provider():
        return _provider().get_unit_by_sensor(sensor_id)
    ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM facility_units WHERE sensor_id=? AND active=1",
            (sensor_id,)
        ).fetchone()
    return dict(row) if row else None


def save_unit(data):
    """Insert or update a facility unit. Returns the unit id."""
    from senaite.pfas import config_history
    config_history.track(None, 'facility_unit', (data or {}).get("id") or (data or {}).get("name") or "new", lambda: get_unit((data or {}).get("id")) if (data or {}).get("id") else None, label=u"Facility unit %s" % ((data or {}).get("name") or ""))
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


# ── Temperature readings ──────────────────────────────────────────────────────

def _requires_correction(unit):
    req = (unit or {}).get("requirements") or _et.seed((unit or {}).get("unit_type"))
    return bool(req.get("correction_factor_required"))


def record_temperature(unit_id, sensor_id, temperature, humidity=None,
                        ts=None, source="sensor"):
    """Store a reading; judge it against the unit's range.

    A unit whose type requires a correction factor (thermometers corrected to
    the NIST reference) is judged on probe + correction, where the
    correction comes from its latest PASSED temperature study on or before the
    reading. The raw probe value is stored as `temperature`, the correction
    beside it."""
    ensure_schema()
    unit = get_unit(unit_id)
    ts = ts or _now()
    in_range = 1
    correction = None
    if unit and temperature is not None and _requires_correction(unit):
        # per reading: a multi-point calibration depends on the temperature read
        cal = calibration(unit_id, ts[:10], unit=unit)
        fixed, _outside = tc.correct(temperature, cal)
        correction = round(fixed - temperature, 4) if fixed is not None else None
    judged = (temperature + correction) if (temperature is not None and correction is not None) \
        else temperature
    if unit and judged is not None:
        lo = unit.get("temp_min")
        hi = unit.get("temp_max")
        if lo is not None and judged < lo:
            in_range = 0
        if hi is not None and judged > hi:
            in_range = 0
    if humidity is not None and unit:
        hlo = unit.get("humidity_min")
        hhi = unit.get("humidity_max")
        if hlo is not None and humidity < hlo:
            in_range = 0
        if hhi is not None and humidity > hhi:
            in_range = 0
    now = _now()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO temperature_readings
            (unit_id, sensor_id, ts, temperature, humidity, in_range, source, created_at,
             correction)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (unit_id, sensor_id, ts, temperature, humidity, in_range, source, now,
              correction))
    return in_range


def _with_corrected(row):
    """A reading as a dict, with `corrected` = probe + correction (or the
    probe value when no correction applied)."""
    r = dict(row)
    t, c = r.get("temperature"), r.get("correction")
    r["corrected"] = (round(t + c, 4) if (t is not None and c is not None) else t)
    return r


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
    return [_with_corrected(r) for r in rows]


# the kinds whose readings are temperatures (rooms add humidity)
READING_KINDS = ("refrigerator", "freezer", "water_bath", "room_sensor")


def daily_means(unit_id, field, date_from=None, date_to=None):
    """{YYYY-MM-DD: mean} of a unit's readings for each day in the window.
    `field` is "temperature" (corrected: probe + its correction) or
    "humidity"."""
    if field not in ("temperature", "humidity"):
        return {}
    ensure_schema()
    value = ("temperature + COALESCE(correction, 0)" if field == "temperature" else "humidity")
    from senaite.pfas import lab_time
    if lab_time.active():
        return _lab_daily_means(unit_id, field, value, date_from, date_to)
    sql = ("SELECT substr(ts, 1, 10) AS day, AVG(%s) FROM temperature_readings "
           "WHERE unit_id=? AND %s IS NOT NULL" % (value, field))
    params = [unit_id]
    if date_from:
        sql += " AND substr(ts, 1, 10) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND substr(ts, 1, 10) <= ?"
        params.append(date_to)
    sql += " GROUP BY day"
    with _connect() as conn:
        return dict((r[0], r[1]) for r in conn.execute(sql, params).fetchall())


def _lab_daily_means(unit_id, field, value, date_from, date_to):
    """daily_means by the laboratory's day: a reading's stamp is UTC, so the
    readings are fetched a day either side of the window and each counted on
    the day its stamp falls on the laboratory's clock."""
    from datetime import timedelta
    from senaite.pfas import lab_time

    def wider(day, days):
        try:
            return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=days)).date().isoformat()
        except ValueError:
            return day

    sql = ("SELECT ts, %s FROM temperature_readings WHERE unit_id=? AND %s IS NOT NULL"
           % (value, field))
    params = [unit_id]
    if date_from:
        sql += " AND substr(ts, 1, 10) >= ?"
        params.append(wider(date_from, -1))
    if date_to:
        sql += " AND substr(ts, 1, 10) <= ?"
        params.append(wider(date_to, 1))
    sums = {}
    clock = lab_clock()
    with _connect() as conn:
        for row in conn.execute(sql, params).fetchall():
            ts, v = row[0], row[1]
            wall = clock(ts)
            day = wall.date() if wall is not None else lab_time.lab_date(ts, "utc")
            if day is None:
                continue
            day = day.isoformat()
            if (date_from and day < date_from) or (date_to and day > date_to):
                continue
            total, n = sums.get(day, (0.0, 0))
            sums[day] = (total + v, n + 1)
    return dict((day, total / n) for day, (total, n) in sums.items())


def effective_range(unit_lo, unit_hi, storage_ranges):
    """The range a monitored unit is judged against: the tightest of its own
    range and the storage ranges of the method profiles that store samples
    in it, [(lo, hi)]. (lo, hi); either may be None when nothing sets it."""
    los = [v for v in [unit_lo] + [r[0] for r in storage_ranges or []] if v is not None]
    his = [v for v in [unit_hi] + [r[1] for r in storage_ranges or []] if v is not None]
    return (max(los) if los else None), (min(his) if his else None)


def range_conflict(lo, hi):
    """True when the ranges a unit must keep do not overlap (a unit holding
    samples at 0 to 6 C and extracts at -25 to -15 C): no reading can meet
    both, so it is a setting to fix, not a failed reading."""
    return lo is not None and hi is not None and lo > hi


def latest_reading(unit_id):
    ensure_schema()
    with _connect() as conn:
        row = conn.execute("""
            SELECT * FROM temperature_readings
            WHERE unit_id=?
            ORDER BY ts DESC LIMIT 1
        """, (unit_id,)).fetchone()
    return _with_corrected(row) if row else None


# ── Temperature studies ───────────────────────────────────────────────────────
#
# The thermometer correction: quarterly, the probe
# is read beside a NIST-traceable reference thermometer -- 4 readings over two
# days. The correction factor is the difference between the two averages,
# NIST minus probe, and is added to the probe's readings until the next study.

STUDY_POINTS = 4
STUDY_MIN_DAYS = 2


def study_correction(points):
    """NIST average minus probe average over a study's paired readings, or
    None until all STUDY_POINTS pairs are in."""
    pairs = [(p.get("sensor_reading"), p.get("nist_reading")) for p in points or []
             if p.get("sensor_reading") is not None and p.get("nist_reading") is not None]
    if len(pairs) < STUDY_POINTS:
        return None
    probe = sum(a for a, _b in pairs) / float(len(pairs))
    nist = sum(b for _a, b in pairs) / float(len(pairs))
    return round(nist - probe, 3)


def study_point_changes(study_id):
    """Every change to a study's recorded readings, oldest first."""
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM temperature_study_point_changes WHERE study_id=?
            ORDER BY changed_at, id
        """, (study_id,)).fetchall()
    return list(map(dict, rows))


def current_correction(unit_id, as_of=None):
    """{"correction", "study_id", "study_date"} from the unit's latest PASSED
    study dated on or before `as_of`, or None."""
    ensure_schema()
    as_of = as_of or _lab_now()[:10]
    with _connect() as conn:
        rows = conn.execute("""
            SELECT id, study_date FROM temperature_studies
            WHERE unit_id=? AND status='pass' AND study_date<=?
            ORDER BY study_date DESC, id DESC
        """, (unit_id, as_of)).fetchall()
    for r in rows:
        r = dict(r)
        st = get_study(r["id"])
        cf = study_correction((st or {}).get("points"))
        if cf is not None:
            return {"correction": cf, "study_id": r["id"], "study_date": r["study_date"]}
    return None

def _model(unit):
    req = (unit or {}).get("requirements") or _et.seed((unit or {}).get("unit_type"))
    return _et.normalise(req, (unit or {}).get("unit_type")).get("correction_model") or tc.SINGLE


def unit_working_temps(unit):
    return _et.working_temps((unit or {}).get("working_temps_json"))


def _studies_with_points(unit_id):
    out = []
    for s in list_studies(unit_id):
        det = get_study(s["id"]) or {}
        out.append(dict(s, points=det.get("points") or []))
    return out


def calibration(unit_id, as_of=None, unit=None):
    """The correction in force for a unit on a date (temp_calibration): a
    multi-point calibration over its working temperatures, or its single
    factor ({"model": "single", "correction", "study_id", "study_date"})."""
    unit = unit if unit is not None else get_unit(unit_id)
    as_of = as_of or _lab_now()[:10]
    if _model(unit) == tc.MULTI:
        return tc.in_force(_studies_with_points(unit_id), unit_working_temps(unit), as_of)
    return tc.single(current_correction(unit_id, as_of))


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
                 study_date=None, tolerance=1.0, notes=None, reference_uid=None,
                 study_temp=None):
    """A new study. `reference_uid` names the registered reference thermometer
    (kind reference_thermometer) it is read against, when there is one;
    `study_temp` the working temperature it is done at (multi-point)."""
    ensure_schema()
    now = _now()
    study_date = study_date or _lab_now()[:10]
    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO temperature_studies
            (unit_id, study_date, operator, nist_serial, nist_cert_date,
             tolerance, status, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (unit_id, study_date, operator, nist_serial, nist_cert_date,
              tolerance, "pending", notes, now))
        study_id = cur.lastrowid
        if reference_uid:
            conn.execute("UPDATE temperature_studies SET reference_uid=? WHERE id=?",
                         (reference_uid, study_id))
        if study_temp is not None:
            conn.execute("UPDATE temperature_studies SET study_temp=? WHERE id=?",
                         (study_temp, study_id))
        for i in range(1, STUDY_POINTS + 1):
            conn.execute("""
                INSERT INTO temperature_study_points (study_id, time_point)
                VALUES (?,?)
            """, (study_id, i))
    return study_id


def save_study_point(study_id, time_point, sensor_reading, nist_reading,
                     recorded_at=None, entered_by=None):
    """Record one paired reading. A reading already recorded that is changed
    keeps its previous values, who changed it and when, in
    temperature_study_point_changes."""
    ensure_schema()
    recorded_at = recorded_at or _lab_now()
    deviation = None
    passed = None
    if sensor_reading is not None and nist_reading is not None:
        deviation = round(sensor_reading - nist_reading, 4)
    with _connect() as conn:
        study = conn.execute(
            "SELECT tolerance FROM temperature_studies WHERE id=?", (study_id,)
        ).fetchone()
        if study and deviation is not None:
            # dict() first -- a unicode key on a Row raises; see _connect.
            passed = 1 if abs(deviation) <= float(dict(study)["tolerance"]) else 0
        prev = conn.execute("""
            SELECT sensor_reading, nist_reading, recorded_at, entered_by
            FROM temperature_study_points WHERE study_id=? AND time_point=?
        """, (study_id, time_point)).fetchone()
        old = dict(prev) if prev else {}
        had = old.get("sensor_reading") is not None or old.get("nist_reading") is not None
        changed = (old.get("sensor_reading"), old.get("nist_reading")) != (sensor_reading, nist_reading)
        if had and changed:
            conn.execute("""
                INSERT INTO temperature_study_point_changes
                (study_id, time_point, old_sensor, old_nist, old_recorded_at,
                 old_entered_by, changed_by, changed_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (study_id, time_point, old.get("sensor_reading"), old.get("nist_reading"),
                  old.get("recorded_at"), old.get("entered_by"), entered_by, _now()))
        conn.execute("""
            UPDATE temperature_study_points
            SET sensor_reading=?, nist_reading=?, deviation=?, passed=?, recorded_at=?,
                entered_by=?
            WHERE study_id=? AND time_point=?
        """, (sensor_reading, nist_reading, deviation, passed, recorded_at,
              entered_by, study_id, time_point))
        _refresh_study_status(conn, study_id)


def _refresh_study_status(conn, study_id):
    """pending until every paired reading is in AND they span STUDY_MIN_DAYS
    days (4 readings over two days); then pass if every pair is within the
    study tolerance, else fail."""
    rows = conn.execute(
        "SELECT passed, recorded_at FROM temperature_study_points WHERE study_id=?",
        (study_id,)).fetchall()
    # dict() first: a unicode key on a sqlite3.Row raises -- see _connect.
    pts = list(map(dict, rows))
    done = [d for d in pts if d.get("passed") is not None]
    filled = [d.get("passed") for d in done]
    days = set((d.get("recorded_at") or "")[:10] for d in done)
    if len(filled) < max(len(pts), STUDY_POINTS) or len(days) < STUDY_MIN_DAYS:
        status = "pending"
    elif all(v == 1 for v in filled):
        status = "pass"
    else:
        status = "fail"
    conn.execute(
        "UPDATE temperature_studies SET status=? WHERE id=?",
        (status, study_id)
    )


# ── Balance verifications ─────────────────────────────────────────────────────

# ── Weight sets (calibrated by an external metrology laboratory) ─────────────

def calibration_required(weight_set):
    """Whether a weight set owes an external calibration: it does unless the
    laboratory switched that off for the set (a row with no value requires it)."""
    return (weight_set or {}).get("calibration_required") not in (0, "0", False)


def save_weight_set(data):
    """Upsert a reference weight set. `data["id"]` absent/None creates one.
    A set saved without `calibration_required` requires its calibration."""
    from senaite.pfas import config_history
    ensure_schema()
    now = _now()
    wid = data.get("id") or uuid.uuid4().hex
    config_history.track(None, 'weight_set', wid, lambda: get_weight_set(wid),
                         label=u"Weight set %s" % (data.get("set_id") or u""))
    cols = ("set_id", "description", "weight_class", "serial_number", "cal_lab",
            "cal_lab_accreditation", "cal_cert_number", "cal_date",
            "cal_due_date", "nist_traceable", "calibration_required", "active", "notes")
    data = dict(data, calibration_required=1 if calibration_required(data) else 0)
    vals = [data.get(c) for c in cols]
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM weight_sets WHERE id=?",
                              (wid,)).fetchone()
        if exists:
            conn.execute(
                "UPDATE weight_sets SET %s WHERE id=?"
                % ", ".join("%s=?" % c for c in cols), vals + [wid])
        else:
            conn.execute(
                "INSERT INTO weight_sets (id, %s, created_at) VALUES (%s)"
                % (", ".join(cols), ", ".join(["?"] * (len(cols) + 2))),
                [wid] + vals + [now])
    return wid


def list_weight_sets(active_only=True):
    ensure_schema()
    with _connect() as conn:
        sql = "SELECT * FROM weight_sets"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY set_id"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_weight_set(weight_set_id):
    ensure_schema()
    if not weight_set_id:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM weight_sets WHERE id=?",
                           (weight_set_id,)).fetchone()
    return dict(row) if row else None


# ── Pipette calibration ──────────────────────────────────────────────────────

def quarter_due(cal_date):
    """An in-house pipette calibration is due once in each calendar quarter:
    one dated in Q4 2026 makes the next due in Q1 2027, by its last day.
    Returns (u"Q1 2027", u"2027-03-31"), or (None, None) for a date it
    cannot read."""
    import calendar
    try:
        y, m = int(cal_date[:4]), int(cal_date[5:7])
    except (TypeError, ValueError):
        return None, None
    if not 1 <= m <= 12:
        return None, None
    q = (m - 1) // 3 + 2
    if q > 4:
        q, y = 1, y + 1
    end = q * 3
    return u"Q%d %d" % (q, y), u"%04d-%02d-%02d" % (y, end, calendar.monthrange(y, end)[1])


def save_pipette_calibration(data):
    """Record a pipette calibration — internal quarterly check or external."""
    ensure_schema()
    cols = ("unit_id", "kind", "cal_date", "due_date", "operator", "provider",
            "provider_accreditation", "cert_number", "balance_unit_id",
            "weight_set_id", "as_found_pct", "tolerance_pct", "passed", "notes",
            "measurements_json", "water_temp")
    vals = [data.get(c) for c in cols]
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO pipette_calibrations (%s, created_at) VALUES (%s)"
            % (", ".join(cols), ", ".join(["?"] * (len(cols) + 1))),
            vals + [_now()])
        return cur.lastrowid


def list_pipette_calibrations(unit_id=None, limit=50):
    ensure_schema()
    with _connect() as conn:
        if unit_id:
            rows = conn.execute(
                "SELECT * FROM pipette_calibrations WHERE unit_id=? "
                "ORDER BY cal_date DESC, id DESC LIMIT ?",
                (unit_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pipette_calibrations "
                "ORDER BY cal_date DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_pipette_calibration_in_force(unit_id, as_of):
    """The calibration covering `as_of`, or None.

    "In force" means calibrated on or before the date and not yet due. Judged
    against the date of USE, not today — the same rule the water log and the
    reagent expiry follow, and for the same reason: a run performed while the
    pipette was in calibration does not stop being defensible later.

    Ordered by `cal_date` AND `id`, so two records on one day resolve
    deterministically.
    """
    ensure_schema()
    if not unit_id or not as_of:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pipette_calibrations WHERE unit_id=? AND cal_date<=? "
            "ORDER BY cal_date DESC, id DESC LIMIT 1",
            (unit_id, as_of)).fetchone()
    if not row:
        return None
    rec = dict(row)
    due = rec.get("due_date") or ""
    rec["in_force"] = bool(not due or due >= as_of)
    return rec


def get_balance_verification_for_date(unit_id, verified_date):
    """The balance verification for a given day, or None. Day-of, by design:
    a balance is verified per working day, and a sample weighed on a day with no
    verification has no established mass provenance."""
    ensure_schema()
    if not unit_id or not verified_date:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM balance_verifications WHERE unit_id=? AND "
            "verified_date=? ORDER BY id DESC LIMIT 1",
            (unit_id, verified_date)).fetchone()
    return dict(row) if row else None


def balance_verified_on(unit_id, verified_date):
    """(ok, note) for weighing on this balance that day: a verification on
    record AND passed. A failed verification is not a verified balance."""
    ver = get_balance_verification_for_date(unit_id, verified_date)
    if not ver:
        return False, u"NOT checked today"
    if not ver.get("passed"):
        return False, u"check FAILED today"
    return True, u"checked today"


def unit_by_serial(serial):
    """A facility unit by its serial number, or None.

    The extraction record captures equipment as free-text SERIAL NUMBERS
    (`equipment_sns`); this join turns one into a registered unit whose
    calibration can be asked about.
    """
    if not serial:
        return None
    if _provider():
        return _provider().unit_by_serial(serial)
    ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM facility_units WHERE serial_number=? LIMIT 1",
            (str(serial).strip(),)).fetchone()
    return dict(row) if row else None


# The internal check each kind owes on its type's frequency:
# a balance its verification, a pipette its calibration, a cold store or room
# its temperature-mapping study, an eye wash its log.
_LAST_CHECK = {
    "balance_analytical": ("balance_verifications", "verified_date"),
    "balance_prep": ("balance_verifications", "verified_date"),
    "pipette": ("pipette_calibrations", "cal_date"),
    "refrigerator": ("temperature_studies", "study_date"),
    "freezer": ("temperature_studies", "study_date"),
    "water_bath": ("temperature_studies", "study_date"),
    "room_sensor": ("temperature_studies", "study_date"),
    "thermometer": ("temperature_studies", "study_date"),
    "ir_gun": ("temperature_studies", "study_date"),
    "nitrogen_evaporator": ("temperature_studies", "study_date"),
    "eyewash": ("eyewash_logs", "log_date"),
    "water_system": ("water_qc_logs", "log_date"),
    "saa": ("waste_logs", "log_date"),
}


def last_check_date(unit_id, kind):
    """The date of the last internal check recorded for a unit, or None."""
    table = _LAST_CHECK.get(kind)
    if not table or not unit_id:
        return None
    ensure_schema()
    if table[0] == "temperature_studies":
        unit = get_unit(unit_id)
        if _model(unit) == tc.MULTI:
            # each working temperature is due on its own: the unit is due
            # when any is (none studied yet: no record)
            temps = unit_working_temps(unit)
            return tc.oldest(tc.last_study_dates(_studies_with_points(unit_id), temps), temps) \
                if temps else None
    extra = " AND status!='pending'" if table[0] == "temperature_studies" else ""
    with _connect() as conn:
        row = conn.execute("SELECT MAX(%s) FROM %s WHERE unit_id=?%s" % (table[1], table[0], extra),
                           (unit_id,)).fetchone()
    return (row[0] or None) if row else None


# Unit types whose measurements a reported result depends on, and which therefore
# owe a traceable calibration. Everything else is recorded as used and nothing more.
CALIBRATED_UNIT_TYPES = ("balance_analytical", "balance_prep", "pipette")


def uncalibrated_weight_sets(unit_id, as_of):
    """The identifiers of the weight sets behind a unit's calibration on a
    date whose calibration is not required: what a batch record must say."""
    out = []
    for r in equipment_provenance(unit_id, as_of).get("records") or []:
        d = r.get("data") or {}
        if r.get("type") == "weight_set" and not calibration_required(d) and d.get("set_id") not in out:
            out.append(d.get("set_id"))
    return out


def equipment_provenance(unit_id, as_of):
    """The calibration chain for one piece of equipment, as of a date.

    Returns {unit, kind, records: [...], problems: [...]} where every branch ends
    the same way the reagent chain does -- at someone else's accredited
    measurement, or at a problem:

        balance  -> verification for that DAY -> weight set -> metrology lab cert
        pipette  -> calibration in force      -> (internal: balance + weight set
                                                  -> metrology lab cert)

    Problems are phrased for a reader, not a developer, because they surface on a
    certificate and in the release gate.
    """
    unit = get_unit(unit_id) if unit_id else None
    out = {"unit": unit, "kind": (unit or {}).get("unit_type") or u"",
           "records": [], "problems": [], "warnings": []}
    if unit is None:
        out["warnings"].append(u"equipment is not registered under Equipment")
        return out

    name = unit.get("name") or unit.get("id")
    ut = unit.get("unit_type") or ""

    def _weight_set_chain(weight_set_id, why):
        ws = get_weight_set(weight_set_id)
        if not weight_set_id or ws is None:
            out["problems"].append(
                u"%s: no reference weight set recorded, so the %s cannot be "
                u"traced to a calibrated standard" % (name, why))
            return
        out["records"].append({"type": "weight_set", "data": ws})
        if not calibration_required(ws):
            # the laboratory's recorded choice: no certificate is demanded, and
            # the record says the set was not calibrated
            out["warnings"].append(
                u"weight set %s is not calibrated: its calibration is not required"
                % ws.get("set_id"))
            return
        if not ws.get("cal_cert_number") or not ws.get("cal_lab"):
            out["problems"].append(
                u"weight set %s has no external calibration certificate — a "
                u"metrology laboratory must calibrate it" % ws.get("set_id"))
        due = ws.get("cal_due_date") or ""
        if due and due < as_of:
            out["problems"].append(
                u"weight set %s calibration expired %s, before it was used on %s"
                % (ws.get("set_id"), due, as_of))

    # WHICH equipment owes a calibration record is a property of its TYPE, not of
    # everything that touched the sample. A balance and a pipette make the
    # measurements a result depends on, so each must trace to a calibrated
    # standard. A centrifuge, vortex mixer, cryogenic mill or shaker measures
    # nothing and has no calibration standard to trace to -- demanding one would
    # be a check that can never be satisfied.
    if ut not in CALIBRATED_UNIT_TYPES:
        out["records"].append({"type": "no_calibration_required",
                               "data": {"unit_type": ut, "name": name}})
        return out

    if ut in ("balance_analytical", "balance_prep"):
        ver = get_balance_verification_for_date(unit_id, as_of)
        if not ver:
            out["problems"].append(
                u"%s has no balance check for %s, the day it was used"
                % (name, as_of))
        else:
            out["records"].append({"type": "balance_verification", "data": ver})
            if not ver.get("passed"):
                out["problems"].append(
                    u"the balance check for %s on %s FAILED"
                    % (name, as_of))
            _weight_set_chain(ver.get("weight_set_id"), u"verification")
    elif ut == "pipette":
        cal = get_pipette_calibration_in_force(unit_id, as_of)
        if not cal:
            out["problems"].append(
                u"%s has no calibration record covering %s" % (name, as_of))
        else:
            out["records"].append({"type": "pipette_calibration", "data": cal})
            if not cal.get("in_force"):
                out["problems"].append(
                    u"%s calibration was due %s, before it was used on %s"
                    % (name, cal.get("due_date"), as_of))
            if not cal.get("passed"):
                out["problems"].append(
                    u"the %s calibration dated %s FAILED"
                    % (name, cal.get("cal_date")))
            if (cal.get("kind") or "") == "external":
                if not cal.get("cert_number") or not cal.get("provider"):
                    out["problems"].append(
                        u"%s external calibration names no provider or "
                        u"certificate number" % name)
            else:
                # An internal check is a measurement this lab made, so it has to
                # carry its own provenance: the balance and the weight set used.
                _weight_set_chain(cal.get("weight_set_id"),
                                  u"in-house pipette check")
                if not cal.get("balance_unit_id"):
                    out["problems"].append(
                        u"%s in-house calibration does not record which balance "
                        u"was used" % name)
    return out


def save_balance_verification(unit_id, operator, verified_date, points, notes=None,
                              weight_set_id=None, portal=None, tolerance_pct=None):
    """points: list of {nominal_g, label, actual_g}, in grams.

    Acceptance is the balance TYPE's tolerance, % of nominal ("Balances should always be in g with acceptable tolerances of 0.2%";). The caller passes the type's `tolerance_pct`; without one the lab's
    stated 0.2 % applies. The absolute tolerance each point was judged against
    is stored with it, so a record shows what it passed against. `portal` is
    accepted for older callers.
    """
    ensure_schema()
    pct = float(tolerance_pct) if tolerance_pct else _et.BALANCE_TOLERANCE_PCT
    now = _now()
    all_passed = True
    processed = []
    for p in points:
        actual = _f(p.get("actual_g"))
        nominal = float(p["nominal_g"])
        tol = round(_et.tolerance_abs(nominal, pct), 9)
        dev = round(actual - nominal, 6) if actual is not None else None
        passed = (1 if _et.within(nominal, actual, pct) else 0) if actual is not None else None
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
            (unit_id, verified_date, operator, passed, notes, weight_set_id,
             created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (unit_id, verified_date, operator, 1 if all_passed else 0, notes,
              weight_set_id, now))
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
            """, (d["id"],)).fetchall()   # d, not r: see _connect
            d["points"] = [dict(p) for p in pts]
            result.append(d)
    return result


# ── Water QC ──────────────────────────────────────────────────────────────────

CONDUCTIVITY_UNITS = (("uS/cm", u"\u00b5S/cm"), ("MOhm.cm", u"M\u03a9\u00b7cm"))


def conductivity_us(reading, unit):
    """A reading in the water system's unit as conductivity in uS/cm (a
    resistivity in MOhm.cm is its reciprocal); None when it cannot be."""
    if reading is None:
        return None
    if unit == "MOhm.cm":
        return (1.0 / reading) if reading > 0 else None
    return reading


def save_water_qc(operator, conductivity, toc, log_date=None, log_time=None,
                  conductivity_max=None, toc_max=None, notes=None, conductivity_entered=None,
                  unit_id=None):
    ensure_schema()
    now, lab_now = _now(), _lab_now()
    log_date = log_date or lab_now[:10]
    log_time = log_time or lab_now[11:16]
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
             conductivity_max, toc_max, passed, notes, created_at, conductivity_entered, unit_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (log_date, log_time, operator, conductivity, toc,
              c_max, t_max, passed, notes, now, conductivity_entered, unit_id or None))
    return passed


def get_water_qc_for_date(log_date):
    """The Type 1 water QC entry in force for `log_date`, or None.

    THE single definition of "was the in-house water system verified that day",
    shared by the prepared-standard parentage walk and the facility dashboard.
    Water produced in house has no manufacturer to trace to: the water QC log
    IS its provenance.

    Ordered by `log_time` AND `id`: two entries in the same minute must not
    make the "latest" arbitrary, or a stale PASS could win over a later FAIL.
    """
    ensure_schema()
    if not log_date:
        return None
    with _connect() as conn:
        row = conn.execute("""
            SELECT * FROM water_qc_logs WHERE log_date=?
            ORDER BY log_time DESC, id DESC LIMIT 1
        """, (log_date,)).fetchone()
    return dict(row) if row else None


def list_water_qc(limit=30):
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM water_qc_logs ORDER BY log_date DESC, log_time DESC, id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Waste logs ────────────────────────────────────────────────────────────────

def save_waste_log(unit_id, operator, condition, log_date=None,
                   log_time=None, notes=None):
    ensure_schema()
    now, lab_now = _now(), _lab_now()
    log_date = log_date or lab_now[:10]
    log_time = log_time or lab_now[11:16]
    with _connect() as conn:
        conn.execute("""
            INSERT INTO waste_logs
            (unit_id, log_date, log_time, operator, condition, notes, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (unit_id, log_date, log_time, operator, condition, notes, now))


def _named_logs(table, unit_id, limit):
    """A log's newest rows (same-minute entries newest first), each with its
    unit's name from the unit provider (the instruments)."""
    ensure_schema()
    sql = "SELECT * FROM %s%s ORDER BY log_date DESC, log_time DESC, id DESC LIMIT ?" % (
        table, " WHERE unit_id=?" if unit_id else "")
    with _connect() as conn:
        rows = conn.execute(sql, (unit_id, limit) if unit_id else (limit,)).fetchall()
    names = dict((u["id"], u["name"]) for u in list_units(active_only=False))
    from senaite.pfas.sqlite_rows import as_dicts
    return [dict(r, unit_name=names.get(r["unit_id"])) for r in as_dicts(rows)]


def list_waste_logs(unit_id=None, limit=30):
    return _named_logs("waste_logs", unit_id, limit)


# ── Eye wash logs ─────────────────────────────────────────────────────────────

def save_eyewash_log(unit_id, operator, working, temperature=None,
                     log_date=None, log_time=None,
                     temp_min=None, temp_max=None, notes=None):
    ensure_schema()
    now, lab_now = _now(), _lab_now()
    log_date = log_date or lab_now[:10]
    log_time = log_time or lab_now[11:16]
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
    return _named_logs("eyewash_logs", unit_id, limit)


# ── Dashboard summary ─────────────────────────────────────────────────────────

def eyewash_status(last_log, req, today):
    """A station's checklist status from its latest log entry: "no_data",
    "out_of_range" (it failed), "due" once its type's frequency has passed
    since that entry (equipment_types.due), else "ok". With no frequency
    entered, an entry older than today is "pending" review."""
    if not last_log:
        return "no_data"
    if not last_log.get("passed"):
        return "out_of_range"
    if (req or {}).get("cal_frequency_days"):
        st = _et.due(req, last_log.get("log_date"), today=today)["internal"]["status"]
        return "due" if st == "overdue" else "ok"
    return "pending" if (last_log.get("log_date") or "") < today else "ok"


def dashboard_summary():
    """Return one status row per unit for the daily checklist dashboard."""
    ensure_schema()
    from datetime import timedelta
    units = list_units(active_only=True)
    today = _lab_now()[:10]
    overdue_hours = 25  # flag if no reading in 25 hours
    cutoff_ts = (datetime.utcnow() - timedelta(hours=overdue_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    result = []
    for u in units:
        if u["unit_type"] in _et.NOT_DAILY_KINDS:
            continue          # on the Equipment page by due date, not daily
        row = dict(u)
        ut = u["unit_type"]
        if ut in READING_KINDS:
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
            # `temperature_readings`; the status is the stored `passed`
            # verdict (the station runs AND its water is tepid, ISO 17025 §6.3).
            #
            # Periodic, not daily: §6.4 puts eye wash on its own cadence, so an
            # older entry is reported as `pending` for review rather than
            # `overdue` against the 25-hour sensor window.
            with _connect() as conn:
                # `id DESC` is a REQUIRED tiebreak: log_time is only HH:MM, so
                # two entries in the same minute tie, and a re-test after a
                # failed check must report the later entry.
                ew = conn.execute("""
                    SELECT * FROM eyewash_logs
                    WHERE unit_id=?
                    ORDER BY log_date DESC, log_time DESC, id DESC
                    LIMIT 1
                """, (u["id"],)).fetchone()
            ew = dict(ew) if ew else None   # unicode key on a Row: see _connect
            row["last_eyewash"] = ew
            row["status"] = eyewash_status(ew, u.get("requirements") or {}, today)
        elif ut in ("balance_analytical", "balance_prep"):
            with _connect() as conn:
                bv = conn.execute("""
                    SELECT * FROM balance_verifications
                    WHERE unit_id=? AND verified_date=?
                    ORDER BY created_at DESC LIMIT 1
                """, (u["id"], today)).fetchone()
            bv = dict(bv) if bv else None   # unicode key on a Row: see _connect
            row["last_balance"] = bv
            if not bv:
                row["status"] = "pending"
            elif bv["passed"]:
                row["status"] = "ok"
            else:
                row["status"] = "out_of_range"
        elif ut == "water_system":
            # One definition of "verified today", shared with the
            # prepared-standard parentage walk.
            wq = get_water_qc_for_date(today)
            row["last_water"] = wq
            if not wq:
                row["status"] = "pending"
            elif wq["passed"]:
                row["status"] = "ok"
            else:
                row["status"] = "out_of_range"
        else:
            # A unit type this dashboard does not know how to check must not
            # claim compliance: reaching here means a type was added without a
            # check.
            logger.warning(
                "facility QC: unit %s has type %r with no status check; "
                "reporting no_data rather than OK", u.get("id"), ut)
            row["status"] = "no_data"
        result.append(row)
    return result


# ── API key helpers ───────────────────────────────────────────────────────────

def api_key_matches(expected, given):
    """The ingest key, compared in constant time; an empty or unset key
    never matches."""
    import hmac
    text = "".__class__
    if not expected or not given:
        return False
    if not isinstance(expected, text) or not isinstance(given, text):
        return False
    return hmac.compare_digest(expected.encode("utf-8"), given.encode("utf-8"))


def get_api_key(portal):
    """Read the sensor ingest API key from portal annotations."""
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    return ann.get("senaite.pfas.facility_qc.api_key", "")


def set_api_key(portal, key):
    from senaite.pfas import config_history
    config_history.track(portal, 'facility_api_key', "api_key", lambda: get_api_key(portal), label=u"Sensor ingest API key")
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    ann["senaite.pfas.facility_qc.api_key"] = key


from senaite.pfas.rounding import number as _f


