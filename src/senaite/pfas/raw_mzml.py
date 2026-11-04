# -*- coding: utf-8 -*-
"""Read a converted injection's SRM chromatograms from mzML (raw data).

An mzML (HUPO-PSI) file written by the converter holds one chromatogram per
MRM transition: its precursor and product m/z (isolation window targets,
MS:1000827), a time array in minutes (MS:1000595) and an intensity array
(MS:1000515), base64 of little-endian 32- or 64-bit floats, uncompressed or
zlib (MS:1000574). Only selected-reaction-monitoring chromatograms
(MS:1001473) are returned; a TIC or anything else is left out.

    read_chromatograms(path) -> [{"id", "q1", "q3", "name", "t": [min], "y": [..]}]
    transition_key(q1, q3)   -> (q1, q3) to 0.1 m/z
    match_transition(wanted, available, tol) -> the file's (q1, q3) nearest to
                               `wanted` within `tol` on both, or None

Pure (standard library only); Python 2.7 and 3, so the add-on and the
worker read raw data the same way.
"""
from __future__ import absolute_import, division, unicode_literals

import base64
import re
import struct
import zlib

try:
    from xml.etree import cElementTree as ET
except ImportError:                                         # Python 3.9+
    from xml.etree import ElementTree as ET

SRM = "MS:1001473"
TARGET_MZ = "MS:1000827"
TIME = "MS:1000595"
INTENSITY = "MS:1000515"
FLOAT32, FLOAT64 = "MS:1000521", "MS:1000523"
ZLIB = "MS:1000574"
# the most bytes one decoded array may hold (a chromatogram of a few
# thousand points is kilobytes; this stops a planted file exhausting memory)
MAX_ARRAY_BYTES = 64 * 1024 * 1024


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _accessions(elem):
    return dict((p.get("accession"), p) for p in elem if _local(p.tag) == "cvParam")


def _target(elem, where):
    for child in elem:
        if _local(child.tag) == where:
            for p in child.iter():
                if _local(p.tag) == "cvParam" and p.get("accession") == TARGET_MZ:
                    return float(p.get("value"))
    return None


def _decode(bda):
    acc = _accessions(bda)
    binary = [c for c in bda if _local(c.tag) == "binary"]
    raw = base64.b64decode((binary[0].text or "") if binary else "")
    if ZLIB in acc:
        d = zlib.decompressobj()
        raw = d.decompress(raw, MAX_ARRAY_BYTES)
        if d.unconsumed_tail:
            raise ValueError("a binary array is larger than %d bytes" % MAX_ARRAY_BYTES)
    elif len(raw) > MAX_ARRAY_BYTES:
        raise ValueError("a binary array is larger than %d bytes" % MAX_ARRAY_BYTES)
    size, code = (4, "f") if FLOAT32 in acc else (8, "d")
    n = len(raw) // size
    kind = TIME if TIME in acc else INTENSITY if INTENSITY in acc else None
    return kind, [float(v) for v in struct.unpack("<%d%s" % (n, code), raw[:n * size])]


def read_chromatograms(path):
    out = []
    # default events ("end"): a unicode event name is refused by Python 2
    for _event, elem in ET.iterparse(path):
        if _local(elem.tag) != "chromatogram":
            continue
        if SRM in _accessions(elem):
            arrays = {}
            for bda in elem.iter():
                if _local(bda.tag) == "binaryDataArray":
                    kind, values = _decode(bda)
                    if kind:
                        arrays[kind] = values
            cid = elem.get("id") or ""
            m = re.search(r"name=(\S+)", cid)
            out.append({"id": cid, "q1": _target(elem, "precursor"), "q3": _target(elem, "product"),
                        "name": m.group(1) if m else cid, "t": arrays.get(TIME, []),
                        "y": arrays.get(INTENSITY, [])})
        elem.clear()
    return out


def transition_key(q1, q3):
    return (round(float(q1), 1), round(float(q3), 1))


# float32 storage of the file's m/z: a delta this far past the tolerance still matches
MZ_EPSILON = 1e-4


class AmbiguousTransition(ValueError):
    """Two different file transitions are equally near the wanted one."""


def match_transition(wanted, available, tol):
    """The (q1, q3) in `available` nearest to `wanted`, or None. A candidate
    qualifies when both its Q1 and Q3 differ from the wanted by at most `tol`
    (plus the float32 epsilon); its distance is the larger of the two. Two
    different candidates at the same best distance raise AmbiguousTransition
    naming both."""
    q1, q3 = float(wanted[0]), float(wanted[1])
    limit = float(tol) + MZ_EPSILON
    scored = []
    for c in set((float(a), float(b)) for a, b in available):
        d1, d3 = abs(c[0] - q1), abs(c[1] - q3)
        if d1 <= limit and d3 <= limit:
            scored.append((max(d1, d3), c))
    if not scored:
        return None
    scored.sort()
    best = scored[0]
    tied = [c for d, c in scored if d - best[0] <= MZ_EPSILON]
    if len(tied) > 1:
        raise AmbiguousTransition("{0:.2f} > {1:.2f} and {2:.2f} > {3:.2f} are equally near {4:.2f} > {5:.2f}".format(
            tied[0][0], tied[0][1], tied[1][0], tied[1][1], q1, q3))
    return best[1]
