# -*- coding: utf-8 -*-
"""Injection names: one scheme, built for reading.

    Method _ [Matrix] _ Sample-or-standard _ [QC on the sample] _ Date-or-batch _ [Repeat]

"_" between parts, "-" only inside a part; capitals, digits, "-" and "_"
only, so a name is safe as a file name and selects as one word. Dates are
YYMMDD (a standard's prep date 261001; an extraction batch 261006-01, the
day and its number). A level follows a hyphen: CAL-1, QCS-1, CCC-L, LFB-M,
LFSM-H. The sample is the LIMS sample ID; the matrix is on extracted
injections only. A repeat ends the name: 01, 02 for each CCV / CCB in the
run, DIL10 for a 1:10 dilution, RE1 for a re-injection.

    537_CAL-1_261001 . 537_CCV_261006_02 . 537_GW_LRB_261006-01
    537_GW_GW-0006_LFSM-H_261006-01 . 537_GW_GW-0006_261006-01_DIL10

The description holds the same parts in the same order, "; "-separated, its
dates labelled: "AN1; prep 2026-10-01; CAL-1". The method's and each
matrix's code are the method profile's (qc_name_codes.METHOD, matrix_codes).
Names already issued are never changed. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

_BAD = re.compile(r"[^A-Z0-9-]+")
LEVEL_LETTER = {u"LOW": u"L", u"MID": u"M", u"MEDIUM": u"M", u"HIGH": u"H"}
# seeded method codes for the shipped methods (the lab's examples); a method
# not listed uses its id; the lab edits it on the method profile
METHOD_SEEDS = {u"EPA_537_1": u"537", u"EPA_1633A": u"1633A", u"FDA_32PFAS": u"FDA", u"EPA_533": u"533"}


def clean(part):
    """A part as the scheme writes it: capitals, digits and "-"."""
    p = (u"%s" % (part or u"")).strip().upper().replace(u"_", u"-").replace(u" ", u"-")
    p = _BAD.sub(u"", p)
    return re.sub(u"-+", u"-", p).strip(u"-")


def level_tag(level):
    """1 -> "1"; Low / Mid / High -> L / M / H; anything else cleaned."""
    lv = (u"%s" % (level or u"")).strip()
    if not lv:
        return u""
    try:
        f = float(lv)
        return u"%d" % f if f == int(f) else clean(lv)
    except ValueError:
        return LEVEL_LETTER.get(lv.upper(), clean(lv))


def role_part(role, level=u""):
    tag = level_tag(level)
    return clean(role) + (u"-" + tag if tag else u"")


def name(method, subject, date, matrix=u"", qc=u"", repeat=u""):
    return u"_".join(p for p in (clean(method), clean(matrix), clean(subject), clean(qc),
                                 clean(date), clean(repeat)) if p)


def yymmdd(iso):
    """'2026-10-01' -> '261001'; '' when it is not a date."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", (iso or u"").strip())
    return (m.group(1)[2:] + m.group(2) + m.group(3)) if m else u""


def standard(method, role, prep_iso, level=u"", repeat=u""):
    """A standard's name: 537_CAL-1_261001, 537_CCV_261006_02."""
    return name(method, role_part(role, level), yymmdd(prep_iso), repeat=repeat)


def extracted(method, matrix, subject, batch_code, qc=u"", repeat=u""):
    """An extracted injection: batch QC (subject = its role, e.g. LRB) or a
    sample (subject = its ID; qc = the QC made on it, e.g. LFSM-H)."""
    return name(method, subject, batch_code, matrix=matrix, qc=qc, repeat=repeat)


def batch_code(day_iso, number):
    """An extraction batch: 261006-01."""
    return u"%s-%02d" % (yymmdd(day_iso), int(number))


def next_batch_number(day_iso, issued_codes):
    """The day's next extraction batch number, from the codes already issued."""
    day = yymmdd(day_iso)
    used = [int(c.split(u"-")[1]) for c in issued_codes or []
            if c.startswith(day + u"-") and c.split(u"-")[1].isdigit()]
    return (max(used) if used else 0) + 1


def description(*parts):
    """The parts in name order, "; "-separated (empty parts left out)."""
    return u"; ".join(u"%s" % p for p in parts if p not in (None, u""))


# one-word matrices with a usual short code (the lab edits any seed)
MATRIX_SEEDS = {u"GROUNDWATER": u"GW", u"WASTEWATER": u"WW", u"SEDIMENT": u"SED",
                u"BIOSOLID": u"BS", u"BIOSOLIDS": u"BS", u"SEAFOOD": u"SF"}


def matrix_seed(matrix):
    """A matrix's seeded code: a usual one (Groundwater -> GW), the initials
    of a several-word name (Drinking Water -> DW), else the word (Milk ->
    MILK, Eggs -> EGG)."""
    known = MATRIX_SEEDS.get(clean(matrix))
    if known:
        return known
    words = [w for w in re.split(r"[\s/]+", (matrix or u"").strip()) if w]
    if len(words) > 1:
        return clean(u"".join(w[0] for w in words))
    w = clean(words[0]) if words else u""
    return w[:-1] if len(w) > 3 and w.endswith(u"S") else w


def method_code(profile, method_id):
    v = (((profile or {}).get("qc_name_codes") or {}).get(u"METHOD") or u"").strip()
    return clean(v) or clean(METHOD_SEEDS.get(method_id) or method_id)


def matrix_code(profile, matrix):
    v = (((profile or {}).get("matrix_codes") or {}).get(matrix) or u"").strip()
    return clean(v) or matrix_seed(matrix)


