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

try:
    from senaite.pfas import equipment_types as _et
except ImportError:          # loaded by file path (tests): the module beside this one
    def _load_beside(name):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("pfas_" + name, path)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except ImportError:                          # Python 2
            import imp
            return imp.load_source("pfas_" + name, path)
    _et = _load_beside("equipment_types")

DB_PATH = os.environ.get("PFAS_FACILITY_QC_DB", "/data/qc/facility_monitoring.db")

UNIT_TYPES = [
    ("refrigerator",       "Refrigerator"),
    ("freezer",            "Freezer"),
    ("balance_analytical", "Balance — Analytical"),
    ("balance_prep",       "Balance — Preparatory"),
    ("eyewash",            "Eye Wash Station"),
    ("water_system",       "Type 1 Water System"),
    # A pipette is verified on a PERIOD, not daily: quarterly in house or by an
    # external provider. Its calibration record is what a result's volumetric
    # step traces to (GAPS §38).
    ("pipette",            "Pipette"),
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

# Default balance weight points per type: [nominal_g, label]. Acceptance is
# NOT per point: it is the balance type's tolerance, % of nominal (0.2 %, lab
# 2026-10-03; equipment_types.py), in grams (GAPS §100).
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
        "study_tolerance": STUDY_TOLERANCE_DEFAULT,
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
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'facility_defaults', "facility", lambda: get_facility_defaults(portal), label=u"Facility QC defaults")
    except Exception:
        pass
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
-- leaves this laboratory and becomes someone else's accredited measurement
-- (GAPS §38).
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
# Almost every function here happens to do `dict(row)` first, which is why only
# two sites ever carried the defect -- `list_balance_verifications` and
# `_refresh_study_status` -- and both were unreachable until the first balance
# verification and the first temperature study existed. Convert to a dict before
# reading columns; do not reach for `b"col"`.


# Columns added to tables that already shipped. CREATE TABLE IF NOT EXISTS cannot
# add a column to an existing database, so these are applied explicitly and
# idempotently — an instance that has been collecting balance verifications must
# not lose them to get the weight-set link.
_ADDED_COLUMNS = [
    ("balance_verifications", "weight_set_id", "TEXT"),
    # the thermometer correction applied to a reading (GAPS §101); the raw
    # probe value stays in `temperature`
    ("temperature_readings", "correction", "REAL"),
]


def ensure_schema():
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        for table, column, coltype in _ADDED_COLUMNS:
            have = set()
            try:
                for row in conn.execute("PRAGMA table_info(%s)" % table):
                    have.add(row[1])
            except Exception:
                continue
            if column not in have:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                             % (table, column, coltype))


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ── Unit registry ─────────────────────────────────────────────────────────────

# ── The equipment registry (GAPS §100b) ──────────────────────────────────────
# Inside SENAITE every unit IS a core Instrument (browser/equipment.py
# registers itself here at start-up): a unit's id is the instrument's UID, its
# name / serial / type come from the instrument, its PFAS settings from an
# annotation on it. The readings and verifications below stay in SQLite, keyed
# by that id. Without a provider (tests, scripts) the legacy facility_units
# table answers, so the pure layer keeps working headlessly.
_PROVIDER = None


def set_unit_provider(provider):
    global _PROVIDER
    _PROVIDER = provider


def _provider():
    p = _PROVIDER
    try:
        return p if (p is not None and p.available()) else None
    except Exception:                                       # noqa: BLE001
        return None


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
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(None, 'facility_unit', (data or {}).get("id") or (data or {}).get("name") or "new", lambda: get_unit((data or {}).get("id")) if (data or {}).get("id") else None, label=u"Facility unit %s" % ((data or {}).get("name") or ""))
    except Exception:
        pass
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

def _requires_correction(unit):
    req = (unit or {}).get("requirements") or _et.seed((unit or {}).get("unit_type"))
    return bool(req.get("correction_factor_required"))


def record_temperature(unit_id, sensor_id, temperature, humidity=None,
                        ts=None, source="sensor"):
    """Store a reading; judge it against the unit's range.

    A unit whose type requires a correction factor (thermometers corrected to
    the NIST reference, GAPS §101) is judged on probe + correction, where the
    correction comes from its latest PASSED temperature study on or before the
    reading. The raw probe value is stored as `temperature`, the correction
    beside it."""
    ensure_schema()
    unit = get_unit(unit_id)
    ts = ts or _now()
    in_range = 1
    correction = None
    if unit and temperature is not None and _requires_correction(unit):
        cur = current_correction(unit_id, ts[:10])
        correction = cur["correction"] if cur else None
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
# The thermometer correction (lab, 2026-10-03; GAPS §101): quarterly, the probe
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


def current_correction(unit_id, as_of=None):
    """{"correction", "study_id", "study_date"} from the unit's latest PASSED
    study dated on or before `as_of`, or None."""
    ensure_schema()
    as_of = as_of or _now()[:10]
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
        for i in range(1, STUDY_POINTS + 1):
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
            # dict() first -- a unicode key on a Row raises; see _connect.
            passed = 1 if abs(deviation) <= float(dict(study)["tolerance"]) else 0
        conn.execute("""
            UPDATE temperature_study_points
            SET sensor_reading=?, nist_reading=?, deviation=?, passed=?, recorded_at=?
            WHERE study_id=? AND time_point=?
        """, (sensor_reading, nist_reading, deviation, passed, recorded_at,
              study_id, time_point))
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

def save_weight_set(data):
    """Upsert a reference weight set. `data["id"]` absent/None creates one."""
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(None, 'weight_set', (data or {}).get("id") or (data or {}).get("name") or "new", lambda: get_weight_set((data or {}).get("id")) if (data or {}).get("id") else None, label=u"Weight set %s" % ((data or {}).get("name") or ""))
    except Exception:
        pass
    ensure_schema()
    now = _now()
    wid = data.get("id") or uuid.uuid4().hex
    cols = ("set_id", "description", "weight_class", "serial_number", "cal_lab",
            "cal_lab_accreditation", "cal_cert_number", "cal_date",
            "cal_due_date", "nist_traceable", "active", "notes")
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

def save_pipette_calibration(data):
    """Record a pipette calibration — internal quarterly check or external."""
    ensure_schema()
    cols = ("unit_id", "kind", "cal_date", "due_date", "operator", "provider",
            "provider_accreditation", "cert_number", "balance_unit_id",
            "weight_set_id", "as_found_pct", "tolerance_pct", "passed", "notes")
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
    deterministically (the §10.1 same-minute defect, one field up).
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


def unit_by_serial(serial):
    """A facility unit by its serial number, or None.

    The extraction record captures equipment as free-text SERIAL NUMBERS
    (`equipment_sns`), which were read only by the PDF. This is the join that
    turns one into a registered unit whose calibration can be asked about.
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


# The internal check each kind owes on its type's frequency (GAPS §100):
# a balance its verification, a pipette its calibration, a cold store or room
# its temperature-mapping study, an eye wash its log.
_LAST_CHECK = {
    "balance_analytical": ("balance_verifications", "verified_date"),
    "balance_prep": ("balance_verifications", "verified_date"),
    "pipette": ("pipette_calibrations", "cal_date"),
    "refrigerator": ("temperature_studies", "study_date"),
    "freezer": ("temperature_studies", "study_date"),
    "room_sensor": ("temperature_studies", "study_date"),
    "eyewash": ("eyewash_logs", "log_date"),
}


def last_check_date(unit_id, kind):
    """The date of the last internal check recorded for a unit, or None."""
    table = _LAST_CHECK.get(kind)
    if not table or not unit_id:
        return None
    ensure_schema()
    extra = " AND status!='pending'" if table[0] == "temperature_studies" else ""
    with _connect() as conn:
        row = conn.execute("SELECT MAX(%s) FROM %s WHERE unit_id=?%s" % (table[1], table[0], extra),
                           (unit_id,)).fetchone()
    return (row[0] or None) if row else None


# Unit types whose measurements a reported result depends on, and which therefore
# owe a traceable calibration. Everything else is recorded as used and nothing more.
CALIBRATED_UNIT_TYPES = ("balance_analytical", "balance_prep", "pipette")


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
        out["warnings"].append(u"equipment is not registered in Facility QC")
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
        if not ws.get("cal_cert_number") or not ws.get("cal_lab"):
            out["problems"].append(
                u"weight set %s has no external calibration certificate — a "
                u"metrology laboratory must calibrate it" % ws.get("set_id"))
        due = ws.get("cal_due_date") or ""
        if due and due < as_of:
            out["problems"].append(
                u"weight set %s calibration expired %s, before it was used on %s"
                % (ws.get("set_id"), due, as_of))
        if not ws.get("nist_traceable"):
            out["problems"].append(
                u"weight set %s is not recorded as NIST-traceable"
                % ws.get("set_id"))

    # WHICH equipment owes a calibration record is a property of its TYPE, not of
    # everything that touched the sample. A balance and a pipette make the
    # measurements a result depends on, so each must trace to a calibrated
    # standard. A centrifuge, vortex mixer, cryogenic mill or shaker measures
    # nothing and has no calibration standard to trace to -- demanding one would
    # be a check that can never be satisfied, which is worse than no check.
    #
    # Found by running this against the real released worksheet WS-0005: 9 of its
    # 13 equipment entries were a mill, a mixer, a centrifuge and a shaker, and
    # the first version of this function demanded a weight set from each.
    if ut not in CALIBRATED_UNIT_TYPES:
        out["records"].append({"type": "no_calibration_required",
                               "data": {"unit_type": ut, "name": name}})
        return out

    if ut in ("balance_analytical", "balance_prep"):
        ver = get_balance_verification_for_date(unit_id, as_of)
        if not ver:
            out["problems"].append(
                u"%s has no balance verification for %s, the day it was used"
                % (name, as_of))
        else:
            out["records"].append({"type": "balance_verification", "data": ver})
            if not ver.get("passed"):
                out["problems"].append(
                    u"the balance verification for %s on %s FAILED"
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

    Acceptance is the balance TYPE's tolerance, % of nominal (lab, 2026-10-03:
    "Balances should always be in g with acceptable tolerances of 0.2%"; GAPS
    §100). The caller passes the type's `tolerance_pct`; without one the lab's
    stated 0.2 % applies. The absolute tolerance each point was judged against
    is stored with it, so a record shows what it passed against. This replaced
    per-point absolute tolerances (10 mg at 0.1 mg was 1 %) and the lab-wide
    `balance_tolerance` in grams. `portal` is accepted for older callers.
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


def get_water_qc_for_date(log_date):
    """The Type 1 water QC entry in force for `log_date`, or None.

    THE single definition of "was the in-house water system verified that day".
    It exists because reagent-grade water produced in house has no manufacturer
    to trace to -- the water QC log IS its provenance (GAPS §36), so the
    prepared-standard parentage walk has to ask this question per preparation
    date, and the facility dashboard already asked it with an inline query.

    Ordered by `log_time` AND `id`. Ordering on log_time alone is the defect
    GAPS §10.1 found for the eye wash: two entries in the same minute made the
    "latest" arbitrary, and a stale PASS could win over a later FAIL.
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
        if u["unit_type"] in _et.NOT_DAILY_KINDS:
            continue          # on the Equipment page by due date, not daily
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
            ew = dict(ew) if ew else None   # unicode key on a Row: see _connect
            row["last_eyewash"] = ew
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
            # prepared-standard parentage walk. The inline query this replaces
            # ordered by log_time alone, which is the same-minute tie GAPS §10.1
            # found for the eye wash.
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
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'facility_api_key', "api_key", lambda: get_api_key(portal), label=u"Sensor ingest API key")
    except Exception:
        pass
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    ann["senaite.pfas.facility_qc.api_key"] = key


def _f(v):
    """Convert to float or return None."""
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None
