# -*- coding: utf-8 -*-
"""Site-wide search. "We need a search bar that
allows users to search for anything within the site. Ranging from specific data
sets, equipment or method settings."

One query, several sources, one ranking:

    records           SENAITE's own catalogs through senaite.app.spotlight
                      (samples, batches, worksheets, clients, methods,
                      services, sample types, instruments, reagents ...)
    pages             every sidebar item the user can open (the rendered
                      sidebar is the source, so roles apply by construction)
    method settings   every declared Method Profile section, tab, field and
                      analyte, per method, linked to its tab
    equipment         instruments and equipment types, linked to Equipment
    settings          the lab settings console's declared settings
    limits            regulatory limits; logbook templates

This module is pure: it matches, ranks and builds index entries from plain
data. browser/site_search.py gathers the data and enforces who may see what.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

GROUPS = [("records", u"Records"), ("inventory", u"Reagents & standards"),
          ("pages", u"Pages"), ("equipment", u"Equipment"),
          ("method", u"Method settings"), ("settings", u"Lab settings"),
          ("limits", u"Regulatory limits"), ("logbooks", u"Logbook templates"),
          ("help", u"Help")]
GROUP_LABELS = dict(GROUPS)

# Which Method Profile tab each section form lives on (method_profile_edit.pt:
# form#section-<x> posts _section=<ids>). Recovery Tiers' list is dynamic
# (spike levels per QC type), so its prefix rule is below.
SECTION_PANE = {"rf": "pane-rf", "iso": "pane-iso", "ls": "pane-sur", "sur": "pane-sur",
                "eis_grid": "pane-eis", "salt": "pane-corr", "scorr": "pane-corr", "rtemp": "pane-mtx", "surscope": "pane-sur", "rpdbasis": "pane-rt", "qcnames": "pane-cal",
                "mf": "pane-corr", "mtx": "pane-mtx", "rl": "pane-rl", "al": "pane-rl",
                "qc_comp": "pane-qct", "lbl": "pane-qct", "xbatch": "pane-qct", "blk": "pane-qct", "cal": "pane-cal", "cal_levels": "pane-cal",
                "cal_scale": "pane-cal", "groups": "pane-rt", "tiers": "pane-rt",
                "tiers_lfb": "pane-rt", "dup": "pane-rt", "lfsmd": "pane-rt"}
PANE_LABEL = {"pane-toggles": u"Rule Toggles & QC Run", "pane-qct": u"QC Types",
              "pane-rt": u"Recovery Tiers", "pane-mtx": u"Matrices & Units",
              "pane-corr": u"Sample Corrections", "pane-ami": u"Analyte × Matrix",
              "pane-iso": u"Isomers", "pane-sur": u"Internal Standards",
              "pane-eis": u"SUR Limits", "pane-rl": u"Reporting Limits",
              "pane-rf": u"Reporting", "pane-cal": u"Calibration & CCV",
              "pane-lwf": u"Lab Workflow"}


def pane_for(section_id):
    if section_id in SECTION_PANE:
        return SECTION_PANE[section_id]
    if section_id.startswith("spk_"):
        return "pane-rt"
    return None


# ── matching and ranking ────────────────────────────────────────────────────

_WORD = re.compile(r"[\wµ°.+-]+", re.UNICODE)


def _u(text):
    """Text as unicode: a UTF-8 byte string from a record (Python 2) once
    broke the whole search on its first non-ASCII character."""
    if isinstance(text, bytes):
        return text.decode("utf-8", "replace")
    return u"%s" % (text if text is not None else u"")


def tokens(text):
    return [t for t in _WORD.findall(_u(text or u"").lower()) if t]


def score(item, q):
    """0 when not every query word occurs in the item; otherwise higher for a
    better match (title before keywords; whole title, then a title starting
    with the query, then word starts, then anywhere)."""
    words = tokens(q)
    if not words:
        return 0
    title = _u(item.get("title") or u"").lower()
    hay = u" ".join([title, _u(item.get("subtitle") or u"").lower(),
                     u" ".join(_u(k) for k in item.get("keywords") or []).lower()])
    hay_words = tokens(hay)
    title_words = tokens(title)
    total = 0
    for w in words:
        if w not in hay:
            return 0
        if any(t.startswith(w) for t in title_words):
            total += 30
        elif w in title:
            total += 15
        elif any(t.startswith(w) for t in hay_words):
            total += 8
        else:
            total += 3
    qn = u" ".join(words)
    if title.strip() == qn:
        total += 100
    elif title.startswith(qn):
        total += 50
    return total + item.get("boost", 0)


def rank(items, q, limit_per_group=None):
    """Matching items, best first, grouped in GROUPS order; duplicates (same
    url) kept once. Returns [(group, label, [item])] for non-empty groups."""
    seen, scored = set(), []
    for it in items or []:
        s = score(it, q)
        if not s or (it.get("url") and it["url"] in seen):
            continue
        if it.get("url"):
            seen.add(it["url"])
        scored.append((s, it))
    out = []
    for gid, label in GROUPS:
        g = [it for s, it in sorted(scored, key=lambda x: -x[0]) if it.get("group") == gid]
        if g:
            out.append((gid, label, g[:limit_per_group] if limit_per_group else g))
    return out


# ── index builders ──────────────────────────────────────────────────────────

_SIDEBAR_ITEM = re.compile(
    r'<a\b[^>]*class="pfas-si[^"]*"[^>]*>.*?</a>', re.S)
_HREF = re.compile(r'href="([^"]+)"')
_TITLE = re.compile(r'title="([^"]*)"')
_LABEL = re.compile(r'<span class="pfas-si-label">([^<]*)</span>')
_GROUP = re.compile(r'<span class="pfas-sg-label">([^<]*)</span>')


def _unescape(s):
    return (s or u"").replace(u"&amp;", u"&").replace(u"&#215;", u"×").strip()


def pages_from_sidebar(html):
    """Every link the rendered sidebar offers this user, with its group."""
    out, seen = [], set()
    # split on group headings so each item knows its group
    parts = re.split(r'(<span class="pfas-sg-label">[^<]*</span>)', html or u"")
    group = u""
    for part in parts:
        m = _GROUP.match(part)
        if m:
            group = _unescape(m.group(1))
            continue
        for a in _SIDEBAR_ITEM.findall(part):
            href, label = _HREF.search(a), _LABEL.search(a)
            if not href or not label:
                continue
            url = _unescape(href.group(1))
            if url in seen:
                continue
            seen.add(url)
            title = _TITLE.search(a)
            out.append({"group": "pages", "title": _unescape(label.group(1)),
                        "subtitle": group, "url": url,
                        "keywords": [_unescape(title.group(1))] if title else []})
    return out


def _link(edit_url, pane, **params):
    """edit_url&k=v#pane -- parameters BEFORE the hash: the editor reads the
    hash as the tab id."""
    extra = u"".join(u"&%s=%s" % (k, v) for k, v in sorted(params.items()) if v)
    return u"%s%s#%s" % (edit_url, extra, pane)


def method_settings(method_id, method_name, edit_url, sections, profile, titles=None,
                    columns_of=None):
    """Index entries for one method profile: each tab, each declared section,
    each field / column label, and each analyte (to Analyte x Matrix).

    sections: {id: Section|Table|Collection}; columns_of(section, profile) ->
    [Field] for a section whose columns depend on the profile. A tab ranks
    above a section, a section above one of its fields."""
    out = []
    sub = u"%s (%s)" % (method_name, method_id)
    for pane, label in sorted(PANE_LABEL.items()):
        out.append({"group": "method", "title": u"%s \u203a %s" % (method_name, label),
                    "subtitle": u"Method profile tab", "url": _link(edit_url, pane),
                    "keywords": [method_id], "boost": 60})
    for sid, sec in sorted(sections.items()):
        pane = pane_for(sid)
        if not pane:
            continue
        tab = PANE_LABEL.get(pane, u"")
        out.append({"group": "method", "title": u"%s: %s" % (method_name, sec.title),
                    "subtitle": u"%s \u203a %s" % (sub, tab), "url": _link(edit_url, pane, s=sid),
                    "keywords": [method_id, tab], "boost": 20})
        labels = []
        for g in getattr(sec, "groups", None) or []:
            labels.append(g[0])
            labels.extend(f.label for f in g[1])
        cols = None
        if hasattr(sec, "columns"):
            cols = columns_of(sec, profile) if columns_of else sec.columns
        if isinstance(cols, list):
            labels.extend(c.label for c in cols)
        for lab in sorted(set(l for l in labels if l)):
            out.append({"group": "method", "title": u"%s \u203a %s" % (sec.title, lab),
                        "subtitle": u"%s \u203a %s" % (sub, tab),
                        "url": _link(edit_url, pane, s=sid, f=re.sub(r"\W+", "-", lab.lower())),
                        "keywords": [method_id, method_name]})
    titles = titles or {}
    for kw in profile.get("master_analyte_set") or []:
        out.append({"group": "method", "title": u"%s in %s" % (titles.get(kw, kw), method_name),
                    "subtitle": u"Analyte \u00b7 %s \u203a Analyte \u00d7 Matrix" % sub,
                    "url": _link(edit_url, "pane-ami", a=kw), "keywords": [kw, method_id]})
    return out


def equipment_entries(units, equipment_url, settings_url, kind_labels):
    out = []
    for u in units or []:
        out.append({"group": "equipment", "title": u.get("name") or u"",
                    "subtitle": u" · ".join(x for x in (
                        u.get("type_title"), kind_labels.get(u.get("unit_type"), u""),
                        (u"SN %s" % u["serial_number"]) if u.get("serial_number") else u"",
                        u.get("location")) if x),
                    "url": u"%s?uid=%s" % (settings_url, u.get("id")),
                    "keywords": [u.get("serial_number") or u"", u.get("unit_type") or u"",
                                 u.get("type_title") or u"", u"equipment", u"instrument"]})
    return out


def inventory_entries(reagents, standards, reagents_url, standards_url):
    """Reagent and prepared-standard lots: name, lot, catalogue number,
    supplier / type; each links to its list filtered to that lot."""
    out = []
    for r in reagents or []:
        lot = r.get("lot_number") or u""
        out.append({"group": "inventory", "title": u"%s \u00b7 lot %s" % (r.get("name") or u"", lot),
                    "subtitle": u" \u00b7 ".join(x for x in (u"Reagent", r.get("supplier"),
                                                           r.get("cat_number"), r.get("status")) if x),
                    "url": u"%s?q=%s" % (reagents_url, lot),
                    "keywords": [lot, r.get("cat_number") or u"", r.get("category") or u"", u"reagent"]})
    for s in standards or []:
        lot = s.get("lot_number") or u""
        out.append({"group": "inventory", "title": u"%s \u00b7 lot %s" % (s.get("name") or u"", lot),
                    "subtitle": u" \u00b7 ".join(x for x in (u"Prepared standard", s.get("type"),
                                                           s.get("status")) if x),
                    "url": u"%s?q=%s" % (standards_url, lot),
                    "keywords": [lot, s.get("type") or u"", u"standard"]})
    return out


def help_entries(entries, help_url):
    """The Help dictionary's entries (help_dictionary.ENTRIES): found by their
    term and text, opened on their tab. The top search is the one search;
    the Help page has no box of its own."""
    return [{"group": "help", "title": e["term"], "subtitle": e.get("group") or u"",
             "keywords": tokens(e.get("text") or u""),
             "url": u"%s?entry=%s" % (help_url, e["id"])} for e in entries]


def limit_entries(limits, programs, url):
    out = []
    for l in limits or []:
        prog = (programs.get(l.get("program")) or {}).get("name") or l.get("program") or u""
        out.append({"group": "limits", "title": u"%s %s" % (l.get("label") or l.get("id"), l.get("kind") or u""),
                    "subtitle": u"%s · %s %s · %s" % (prog, l.get("value"), l.get("unit") or u"",
                                                             u", ".join(l.get("matrices") or [])),
                    "url": url, "keywords": list(l.get("analytes") or []) + [u"mcl", u"action level"]})
    return out
