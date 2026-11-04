"""Read a Waters MassLynx `.raw` folder directly, so no vendor converter is
needed to get its MRM chromatograms.

A folder holds one function per MRM transition:
  - `_functns.inf`: 416 bytes per function; scan count uint16 at byte 18,
    Q1 float32 at 160, Q3 float32 at 288 (little endian);
  - `_funcNNN.idx`: 22 bytes per scan; time float32 at byte 12;
  - `_funcNNN.dat`: one uint16 per scan, intensity `(raw >> 3) * 4 ** (raw & 7)`;
  - `_header.txt`: `$$ Acquired Date` and `$$ Acquired Time`.
Function numbers 1 to 99 are written with three digits, 100 and up with four;
file names may be in any case.

Time: the idx time of the first scan is the scheduled window's start in
seconds, every later one is elapsed minutes from it, so
retention time in minutes = t0 / 60 + (t - t0).

Intensity: a word is a 13-bit mantissa and a 3-bit exponent of 4. Above
CEILING a value needs exponent 8 or more, which the 3-bit field stores
modulo 8, with the mantissa still normalised (2048 or more); read as stored,
the apex would be a trough. `exponents` restores the lost 8: a word whose
mantissa is 2048 or more, following a word at exponent 7 or higher, takes
whichever of its exponent and its exponent + 8 lies closer (as a ratio) to
the value before it. With m the trace's maximum, a trace whose apex is still
a trough is flagged overflowed: m at least 4e7 and a point between the first
and the last point at or above half of m below 0.3 * m (the span above
half-maximum of a real peak never dips), because its area is not the peak's.

    is_masslynx(folder) -> bool
    files(folder) -> {lower-cased name: path}
    transitions(folder) -> [(function number, q1, q3)]
    trace(folder, function_number) -> (rt minutes, intensity)
    exponents(raw) -> each word's exponent of 4, the lost 8 restored
    overflowed(y) -> bool
    acquired(folder) -> ISO 8601 string or None
    read_chromatograms(folder) -> [{"id", "q1", "q3", "name", "t", "y", "overflowed"}]

The records have the keys of `raw_mzml.read_chromatograms` plus `overflowed`.
Pure reading, no vendor code. Python 3.
"""
from __future__ import annotations

import datetime
import os
import re
import struct
from typing import Optional

import numpy as np

CEILING = 8191 * 4 ** 7
FUNCTION_RECORD = 416
INDEX_RECORD = 22
COUNT_AT, Q1_AT, Q3_AT, TIME_AT = 18, 160, 288, 12
POINTS_AT, POINTS_MASK = 4, 0x3FFFFF
# a normalised mantissa: every word above exponent 0 holds one of at least NORMALISED
NORMALISED = 2048
EXPONENT_BITS = 8
# a wrapped apex: from m >= WRAP_FLOOR, a dip below DIP_SHARE of m inside the span above SPAN_SHARE of m
WRAP_FLOOR = 4e7
SPAN_SHARE = 0.50
DIP_SHARE = 0.30
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class MassLynxError(Exception):
    """A folder with a missing or short file."""


def files(folder: str) -> dict[str, str]:
    """The folder's files by lower-cased name."""
    return {name.lower(): os.path.join(folder, name) for name in sorted(os.listdir(folder))}


def is_masslynx(folder: str) -> bool:
    """A directory holding `_functns.inf`, in any case."""
    return os.path.isdir(folder) and "_functns.inf" in files(folder)


def _read(folder: str, name: str) -> bytes:
    path = files(folder).get(name)
    if path is None:
        raise MassLynxError("%s: %s is missing" % (os.path.basename(folder), name))
    with open(path, "rb") as fh:
        return fh.read()


def _function_file(number: int, suffix: str) -> str:
    return "_func%0*d.%s" % (3 if number < 100 else 4, number, suffix)


def _function_records(folder: str) -> bytes:
    buf = _read(folder, "_functns.inf")
    if len(buf) % FUNCTION_RECORD:
        raise MassLynxError("%s: _functns.inf is not whole %d-byte records" % (os.path.basename(folder), FUNCTION_RECORD))
    return buf


def transitions(folder: str) -> list[tuple[int, float, float]]:
    """(function number, q1, q3) for every function, in function order."""
    buf = _function_records(folder)
    out = []
    for i in range(len(buf) // FUNCTION_RECORD):
        at = i * FUNCTION_RECORD
        q1 = struct.unpack_from("<f", buf, at + Q1_AT)[0]
        q3 = struct.unpack_from("<f", buf, at + Q3_AT)[0]
        out.append((i + 1, q1, q3))
    return out


def trace(folder: str, function_number: int) -> tuple[np.ndarray, np.ndarray]:
    """(retention time in minutes, intensity) of one function."""
    buf = _function_records(folder)
    if not 1 <= function_number <= len(buf) // FUNCTION_RECORD:
        raise MassLynxError("%s: no function %d" % (os.path.basename(folder), function_number))
    count = struct.unpack_from("<H", buf, (function_number - 1) * FUNCTION_RECORD + COUNT_AT)[0]
    idx_name, dat_name = _function_file(function_number, "idx"), _function_file(function_number, "dat")
    idx, dat = _read(folder, idx_name), _read(folder, dat_name)
    where = os.path.basename(folder)
    if len(idx) % INDEX_RECORD:
        raise MassLynxError("%s: %s is not whole %d-byte records" % (where, idx_name, INDEX_RECORD))
    scans = len(idx) // INDEX_RECORD
    if scans != count:
        raise MassLynxError("%s: %s holds %d scans but _functns.inf says %d" % (where, idx_name, scans, count))
    if len(dat) < 2 * scans:
        raise MassLynxError("%s: %s is shorter than its index" % (where, dat_name))
    if len(dat) > 2 * scans:
        raise MassLynxError("%s: %s is longer than its index" % (where, dat_name))
    if scans == 0:
        return np.zeros(0), np.zeros(0)
    # one point per scan: the data file is read as one value per scan
    points = np.ndarray(scans, "<I", idx, POINTS_AT, INDEX_RECORD) & POINTS_MASK
    if np.any(points != 1):
        raise MassLynxError("%s: %s has scans with more or fewer than one point" % (where, idx_name))
    t = np.ndarray(scans, "<f", idx, TIME_AT, INDEX_RECORD).astype(float)
    raw = np.ndarray(scans, "<H", dat)
    y = (raw >> 3).astype(float) * 4.0 ** exponents(raw)
    return t[0] / 60.0 + (t - t[0]), y


def exponents(raw) -> np.ndarray:
    """Each word's exponent of 4: the stored three bits, plus 8 where the
    value outgrew them. Scan by scan, a word whose mantissa is NORMALISED or
    more, after a word at exponent 7 or higher, takes the stored exponent or
    the stored exponent + 8, whichever value is the nearer ratio to the one
    before it; the encoder never writes a smaller mantissa above exponent 0."""
    raw = np.asarray(raw).astype(np.int64)
    mantissa, out = raw >> 3, (raw & 7).astype(np.int64)
    for i in range(1, len(raw)):
        if out[i - 1] < 7 or mantissa[i] < NORMALISED:
            continue
        before = np.log(max(float(mantissa[i - 1]), 1.0)) + out[i - 1] * np.log(4.0)
        low = np.log(float(mantissa[i])) + out[i] * np.log(4.0)
        high = low + EXPONENT_BITS * np.log(4.0)
        if abs(high - before) < abs(low - before):
            out[i] += EXPONENT_BITS
    return out


def overflowed(y: np.ndarray) -> bool:
    """With m the maximum: m >= 4e7 and a point between the first and the
    last point at or above 0.5 * m that is below 0.3 * m. A real peak never
    dips inside its span above half-maximum; an apex the reading could not
    restore is a trough there. A maximum above CEILING is a restored value,
    not an overflow."""
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return False
    top = float(y.max())
    if top < WRAP_FLOOR:
        return False
    above = np.flatnonzero(y >= SPAN_SHARE * top)
    return bool((y[above[0]:above[-1] + 1] < DIP_SHARE * top).any())


def acquired(folder: str) -> Optional[str]:
    """The acquisition time from `_header.txt` as ISO 8601, or None when the
    header, the date or the time is absent or unreadable."""
    path = files(folder).get("_header.txt")
    if path is None:
        return None
    with open(path, "rb") as fh:
        text = fh.read().decode("latin-1")
    date = re.search(r"^\$\$\s*Acquired Date\s*:\s*(\S+)", text, re.I | re.M)
    clock = re.search(r"^\$\$\s*Acquired Time\s*:\s*(\d{1,2}):(\d{2}):(\d{2})", text, re.I | re.M)
    if not date or not clock:
        return None
    parts = date.group(1).split("-")
    if len(parts) != 3:
        return None
    day, month, year = parts
    month = str(MONTHS.index(month[:3].lower()) + 1) if month[:3].lower() in MONTHS else month
    try:
        when = datetime.datetime(int(year), int(month), int(day), *(int(g) for g in clock.groups()))
    except ValueError:
        return None
    return when.isoformat()


def read_chromatograms(folder: str) -> list[dict]:
    """One record per function, with the keys of `raw_mzml.read_chromatograms`
    plus `overflowed`; time in minutes."""
    records = []
    for number, q1, q3 in transitions(folder):
        t, y = trace(folder, number)
        records.append({"id": "function %d" % number, "q1": q1, "q3": q3, "name": "",
                        "t": t.tolist(), "y": y.tolist(), "overflowed": overflowed(y)})
    return records
