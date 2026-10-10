# -*- coding: utf-8 -*-
"""Study templates: studies the lab designs in the UI (@@pfas-study-designer),
built from generic elements -- no study is coded for one method.

A template:

    {"id": "ST-0001", "name", "method", "matrix" ("" = any), "elements": [...]}

Element types (each {"id", "type", "name", ...}):

  replicates   replicate injections of one role (LFB, ...), grouped by
               SOURCE (how many independent standard sources) x LEVEL
               ([{"label", "value"}] in the matrix's unit); "replicates" per
               cell (blank: set when the cell is assigned). Statistics, each
               switched on with its own limit (blank limit = to be entered):
                 recovery        mean recovery per level, min / max %
                 rsd_within      RSD of each source's replicates, max %
                 rsd_between     RSD between sources per level, max %;
                                 "between_basis": "means" (of the source means)
                                 or "pooled" (all replicates at the level)
  mdl          40 CFR 136 App. B Rev. 2 from the study's spiked replicates
               and blanks (method_studies.mdl_rev2); "spike_role", "blank_role"
  qualitative  a check judged by a person on uploaded evidence
               (chromatograms): "instructions", "accept" (file types); passes
               when at least one file is uploaded and a reviewer passed it
  typed        numbers typed with their evidence (e.g. peak asymmetry):
               "count", "unit", "min", "max", "upload" (a file is required)

A study made from a template keeps a copy of it ("design"), so editing the
template later never changes a study under way. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import math
import re

KEY = "senaite.pfas.study_templates"
TYPES = [
    ("replicates", u"Replicates by source and level"),
    ("mdl", u"MDL (40 CFR 136 App. B Rev. 2)"),
    ("qualitative", u"Qualitative check with uploaded evidence"),
    ("typed", u"Typed values with evidence"),
]
TYPE_LABELS = dict(TYPES)
PASS, FAIL, OPEN = u"pass", u"fail", u"not evaluated"
TO_ENTER = u"to be entered"


# ── the template ──────────────────────────────────────────────────────────
def next_id(templates, prefix=u"ST"):
    nums = [int(t["id"].split("-")[1]) for t in templates or []
            if (t.get("id") or u"").startswith(prefix + u"-") and t["id"].split("-")[1].isdigit()]
    return u"%s-%04d" % (prefix, max(nums or [0]) + 1)


def new_element(etype, existing_ids=()):
    if etype not in TYPE_LABELS:
        raise ValueError(u"unknown element type %s" % etype)
    n = 1
    while u"E%d" % n in set(existing_ids):
        n += 1
    el = {"id": u"E%d" % n, "type": etype, "name": TYPE_LABELS[etype]}
    if etype == "replicates":
        el.update(role=u"LFB", sources=1, levels=[], replicates=None,
                  stats={"recovery": {"on": False, "min": None, "max": None},
                         "rsd_within": {"on": False, "max": None},
                         "rsd_between": {"on": False, "max": None, "basis": u"means"}})
    elif etype == "mdl":
        el.update(spike_role=u"LFB", blank_role=u"MB")
    elif etype == "qualitative":
        el.update(instructions=u"", accept=u"pdf, png, jpg")
    elif etype == "typed":
        el.update(count=1, unit=u"", min=None, max=None, upload=True)
    return el


def _num(v):
    if v is None or (u"%s" % v).strip() == u"":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return False


def parse_levels(text):
    """"25, 50, 100" or "Low=25, High=100" -> ([{"label", "value"}], problems)."""
    out, problems = [], []
    for part in [p.strip() for p in (text or u"").replace(u";", u",").split(u",") if p.strip()]:
        label, _sep, value = part.partition(u"=")
        if not _sep:
            label, value = part, part
        v = _num(value)
        if v is None or v is False or v <= 0:
            problems.append(u"%s is not a level (a value above 0)." % part)
            continue
        out.append({"label": label.strip(), "value": v})
    return out, problems


def levels_text(levels):
    return u", ".join(l["label"] if (u"%s" % l["label"]) == (u"%g" % l["value"])
                      else u"%s=%g" % (l["label"], l["value"]) for l in levels or [])


def problems(template):
    """What stops a template being used (a blank limit does not: it reads
    'to be entered')."""
    out = []
    if not (template.get("name") or u"").strip():
        out.append(u"Name the template.")
    if not template.get("method"):
        out.append(u"Choose the method.")
    if not template.get("elements"):
        out.append(u"Add at least one element.")
    for el in template.get("elements") or []:
        label = el.get("name") or el.get("id")
        if el.get("type") == "replicates":
            if not el.get("levels"):
                out.append(u"%s: give at least one level." % label)
            if int(el.get("sources") or 0) < 1:
                out.append(u"%s: at least one source." % label)
        if el.get("type") == "typed" and int(el.get("count") or 0) < 1:
            out.append(u"%s: at least one value." % label)
    return out


# ── cells: what a study assigns ───────────────────────────────────────────
def source_labels(n):
    return [u"Source %s" % chr(ord("A") + i) for i in range(max(int(n or 0), 0))]


def cells(design):
    """[{"key", "element", "name", "role", "source", "level", "value",
    "replicates"}] -- one assignable part per source x level of each
    replicates element, and the spiked and blank parts of an MDL element."""
    out = []
    for el in (design or {}).get("elements") or []:
        if el.get("type") == "replicates":
            for src in source_labels(el.get("sources")):
                for lv in el.get("levels") or []:
                    out.append({"key": u"%s|%s|%s" % (el["id"], src, lv["label"]),
                                "element": el["id"], "name": el.get("name") or u"",
                                "role": el.get("role") or u"LFB", "source": src,
                                "level": lv["label"], "value": lv["value"],
                                "replicates": el.get("replicates")})
        elif el.get("type") == "mdl":
            for part, role in ((u"spiked", el.get("spike_role") or u"LFB"),
                               (u"blanks", el.get("blank_role") or u"MB")):
                out.append({"key": u"%s|%s" % (el["id"], part), "element": el["id"],
                            "name": u"%s, %s" % (el.get("name") or u"MDL", part), "role": role,
                            "source": u"", "level": u"", "value": None, "replicates": None})
    return out


# ── statistics ────────────────────────────────────────────────────────────
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _rsd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    if not m:
        return None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return 100.0 * sd / abs(m)


def _judge_max(value, limit):
    if value is None:
        return OPEN
    if limit is None:
        return TO_ENTER
    return PASS if round(value, 6) <= limit else FAIL


def _judge_window(value, lo, hi):
    if value is None:
        return OPEN
    if lo is None and hi is None:
        return TO_ENTER
    ok = (lo is None or round(value, 6) >= lo) and (hi is None or round(value, 6) <= hi)
    return PASS if ok else FAIL


def evaluate_replicates(el, rows):
    """`rows` = [{"source", "level", "values": {analyte: value}}]. Returns
    {"rows": [{analyte, level, stat, value, limit, verdict}], "verdict"}."""
    stats = el.get("stats") or {}
    fort = dict((l["label"], l["value"]) for l in el.get("levels") or [])
    analytes = sorted(set(a for r in rows for a in (r.get("values") or {})))
    out = []
    for a in analytes:
        for lv in [l["label"] for l in el.get("levels") or []]:
            at = [r for r in rows if r.get("level") == lv and (r.get("values") or {}).get(a) is not None]
            by_src = {}
            for r in at:
                by_src.setdefault(r.get("source"), []).append(float(r["values"][a]))
            vals = [v for vs in by_src.values() for v in vs]
            if (stats.get("recovery") or {}).get("on"):
                rec = _mean([100.0 * v / fort[lv] for v in vals]) if vals and fort.get(lv) else None
                s = stats["recovery"]
                out.append({"analyte": a, "level": lv, "stat": u"Mean recovery %", "value": rec,
                            "limit": u"%s-%s" % (s.get("min"), s.get("max")),
                            "verdict": _judge_window(rec, s.get("min"), s.get("max"))})
            if (stats.get("rsd_within") or {}).get("on"):
                for src in sorted(by_src):
                    r = _rsd(by_src[src])
                    out.append({"analyte": a, "level": lv, "stat": u"RSD %% within %s" % src,
                                "value": r, "limit": stats["rsd_within"].get("max"),
                                "verdict": _judge_max(r, stats["rsd_within"].get("max"))})
            if (stats.get("rsd_between") or {}).get("on"):
                s = stats["rsd_between"]
                if s.get("basis") == u"pooled":
                    r = _rsd(vals) if len(by_src) > 1 else None
                else:
                    r = _rsd([_mean(v) for v in by_src.values()]) if len(by_src) > 1 else None
                out.append({"analyte": a, "level": lv,
                            "stat": u"RSD %% between sources (%s)" % (
                                u"pooled" if s.get("basis") == u"pooled" else u"of the means"),
                            "value": r, "limit": s.get("max"), "verdict": _judge_max(r, s.get("max"))})
    return {"rows": out, "verdict": combine([r["verdict"] for r in out])}


def evaluate_mdl(results):
    """{analyte: method_studies.mdl_rev2 result} -> rows and a verdict: an
    MDL calculated without notes passes; with notes or none it is open."""
    out = []
    for a, r in sorted((results or {}).items()):
        v = PASS if r.get("verdict") == "calculated" else OPEN
        out.append({"analyte": a, "level": u"", "stat": u"MDL", "value": r.get("mdl"),
                    "limit": u"; ".join(r.get("notes") or []), "verdict": v})
    return {"rows": out, "verdict": combine([r["verdict"] for r in out])}


def evaluate_typed(el, entry, file_present):
    vals = [_num(v) for v in (entry or {}).get("values") or []]
    vals = [v for v in vals if v not in (None, False)]
    n = int(el.get("count") or 1)
    if len(vals) < n:
        return {"verdict": OPEN, "reason": u"type %d value(s)" % n, "values": vals}
    if el.get("upload") and not file_present:
        return {"verdict": OPEN, "reason": u"attach the evidence", "values": vals}
    verdicts = [_judge_window(v, _num(el.get("min")) or None, _num(el.get("max")) or None) for v in vals[:n]]
    return {"verdict": combine(verdicts), "values": vals[:n]}


def evaluate_qualitative(el, entry, files):
    if not files:
        return {"verdict": OPEN, "reason": u"upload the evidence"}
    v = (entry or {}).get("verdict")
    if v not in (PASS, FAIL):
        return {"verdict": OPEN, "reason": u"a reviewer judges the evidence", "files": len(files)}
    return {"verdict": v, "by": (entry or {}).get("by"), "note": (entry or {}).get("note"),
            "files": len(files)}


def combine(verdicts):
    """Every part passes -> pass; any fail -> fail; else not evaluated (a
    limit still to be entered keeps it open)."""
    verdicts = list(verdicts)
    if not verdicts:
        return OPEN
    if FAIL in verdicts:
        return FAIL
    return PASS if all(v == PASS for v in verdicts) else OPEN


# ── storage ───────────────────────────────────────────────────────────────
def load(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(portal).get(KEY) or u"[]")
    except (TypeError, ValueError):
        return []


def save(portal, templates):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[KEY] = json.dumps(templates)


def find(templates, tid):
    for t in templates or []:
        if t.get("id") == tid:
            return t
    return None


def slug(text):
    return re.sub(r"[^a-z0-9]+", u"-", (text or u"").lower()).strip(u"-")


# ── the designer's form (study_designer.py) ───────────────────────────────
def _f(form, el, field):
    return form.get(u"e__%s__%s" % (el["id"], field))


def _on(v):
    return v in (True, u"on", u"1", u"yes", "on")


def _int(v):
    n = _num(v)
    return int(n) if n not in (None, False) else None


def apply_form(template, form):
    """(template', [problem]) from the designer's fields: t__name, t__method,
    t__matrix and e__<element id>__<field>. A malformed number is refused;
    a blank limit is kept as 'to be entered'."""
    t = json.loads(json.dumps(template))          # a copy
    bad = []
    for k in ("name", "method", "matrix"):
        if form.get(u"t__" + k) is not None:
            t[k] = (form.get(u"t__" + k) or u"").strip()

    def number(el, field, label):
        v = _num(_f(form, el, field))
        if v is False:
            bad.append(u"%s: %s is not a number." % (el.get("name") or el["id"], label))
            return None
        return v

    for el in t.get("elements") or []:
        if _f(form, el, "name") is not None:
            el["name"] = (_f(form, el, "name") or u"").strip() or TYPE_LABELS[el["type"]]
        if el["type"] == "replicates":
            el["role"] = _f(form, el, "role") or el.get("role") or u"LFB"
            el["sources"] = _int(_f(form, el, "sources")) or 1
            levels, probs = parse_levels(_f(form, el, "levels"))
            bad.extend(u"%s: %s" % (el["name"], p) for p in probs)
            el["levels"] = levels
            reps = number(el, "replicates", u"replicates")
            el["replicates"] = int(reps) if reps else None
            el["stats"] = {
                "recovery": {"on": _on(_f(form, el, "recovery_on")),
                             "min": number(el, "recovery_min", u"lowest recovery"),
                             "max": number(el, "recovery_max", u"highest recovery")},
                "rsd_within": {"on": _on(_f(form, el, "rsd_within_on")),
                               "max": number(el, "rsd_within_max", u"RSD within a source")},
                "rsd_between": {"on": _on(_f(form, el, "rsd_between_on")),
                                "max": number(el, "rsd_between_max", u"RSD between sources"),
                                "basis": u"pooled" if _f(form, el, "rsd_between_basis") == u"pooled"
                                else u"means"}}
        elif el["type"] == "mdl":
            el["spike_role"] = _f(form, el, "spike_role") or el.get("spike_role") or u"LFB"
            el["blank_role"] = _f(form, el, "blank_role") or el.get("blank_role") or u"MB"
        elif el["type"] == "qualitative":
            el["instructions"] = (_f(form, el, "instructions") or u"").strip()
            el["accept"] = (_f(form, el, "accept") or u"").strip() or u"pdf, png, jpg"
        elif el["type"] == "typed":
            el["count"] = _int(_f(form, el, "count")) or 1
            el["unit"] = (_f(form, el, "unit") or u"").strip()
            el["min"] = number(el, "min", u"lowest value")
            el["max"] = number(el, "max", u"highest value")
            el["upload"] = _on(_f(form, el, "upload"))
    return t, bad
