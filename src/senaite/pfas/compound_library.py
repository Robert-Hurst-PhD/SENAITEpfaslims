# -*- coding: utf-8 -*-
"""The compound library: every native analyte and labelled standard, as the
core Analysis Services hold it.

The owner is the core AnalysisService. Each library fact is a field on it
(the PFAS tab of its edit form, extenders/analysisservice.py):

    keyword          core Keyword
    role             pfas_role: analyte | surrogate | injection_is
    name             pfas_display_name: the compound name instrument exports
                     use; blank means the keyword
    cas              pfas_cas: the CAS Registry Number of a native analyte
                     (a delivery format's own code overrides it in its EDD
                     export profile, never here)
    analog_of        pfas_labelled_analog_of: on a labelled standard, the
                     native it is the isotopically labelled form of (whether
                     that native has a labelled standard of its own in a
                     method follows from the method's surrogate links)
    aliases          pfas_aliases: other names instrument exports use for the
                     compound (a retired supplier code, the linear peak's
                     name, a vendor spelling); each resolves to the keyword
    published_names  pfas_published_names: how a published method names a
                     native where that differs from the keyword (EPA's
                     HFPO-DA for GenX); used to join a method's own tables
    key              pfas_key_analyte: a key analyte by default when the
                     native joins a method (each method's Key analytes list
                     decides)

SENAITE writes the library to the worker's data beside the method profiles
(FILE_NAME), from the services, every time it exports the profiles and
whenever a service changes; the worker reads only that export. The tables
in analyte_reference.py are the install seed (seed_rows), written onto the
services once by the migration.

    build(rows)          the export, from one row per service
    problems(export)     what makes an export unusable (refused, never guessed)
    referenced(profile)  the compounds a method profile names
    missing(export, p)   those the library has no entry for
    accessors            name_to_keyword, synonyms, labelled_names,
                         native_names, names_by_role, analog_map,
                         labelled_keywords, key_keywords, key_names,
                         cas_by_keyword, native_keyword_for

Pure: Python 2.7 and 3, no Zope imports (the worker loads this file from
the add-on, pfas_pipeline.addon).
"""
from __future__ import absolute_import, unicode_literals

import re

FILE_NAME = "compound_library.json"
LIBRARY_V = 1
LABELLED_ROLES = ("surrogate", "injection_is")
ROLES = ("analyte",) + LABELLED_ROLES

# the service fields each library fact is stored in (the PFAS tab)
FIELDS = (
    ("name", "pfas_display_name"),
    ("cas", "pfas_cas"),
    ("analog_of", "pfas_labelled_analog_of"),
    ("aliases", "pfas_aliases"),
    ("published_names", "pfas_published_names"),
    ("key", "pfas_key_analyte"),
)
LIST_FACTS = ("aliases", "published_names")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return ("%s" % value).strip()


def _names(values, own):
    """Distinct non-blank names, in order, without the compound's own keyword
    (a lines field gives a list; text is one name per line)."""
    if not isinstance(values, (list, tuple)):
        values = re.split(r"[\r\n]+", _text(values)) if values else []
    out = []
    for v in values or ():
        v = _text(v)
        if v and v != own and v not in out:
            out.append(v)
    return out


def build(rows):
    """The export: {"library_v", "compounds": {keyword: facts}, "problems"}.

    One row per service ({keyword, role} and the FIELDS facts); a row with
    no keyword or no PFAS role is not part of the library. A blank display
    name is the keyword."""
    compounds = {}
    for row in rows or ():
        kw = _text(row.get("keyword"))
        role = _text(row.get("role"))
        if not kw or role not in ROLES:
            continue
        compounds[kw] = {
            "role": role,
            "name": _text(row.get("name")) or kw,
            "cas": _text(row.get("cas")),
            "analog_of": _text(row.get("analog_of")),
            "aliases": _names(row.get("aliases"), kw),
            "published_names": _names(row.get("published_names"), kw),
            "key": bool(row.get("key")),
        }
    export = {"library_v": LIBRARY_V, "compounds": compounds}
    export["problems"] = problems(export)
    return export


def compounds(export):
    return (export or {}).get("compounds") or {}


def unusable(export):
    """Why an export cannot be read at all (not a library, another version),
    or None."""
    if not isinstance(export, dict) or not isinstance(export.get("compounds"), dict):
        return "it is not a compound library export"
    if export.get("library_v") != LIBRARY_V:
        return "it was written as version %r; this code reads version %d" % (
            export.get("library_v"), LIBRARY_V)
    return None


def problems(export):
    """Every way the library names a compound ambiguously or links it to
    nothing, as sentences; [] when it is usable.

    A name (display name, alias or published name) that two compounds claim,
    or that is another compound's keyword, would make an instrument row or a
    method table resolve to whichever came last; a labelled standard linked
    to a native the library does not hold links to nothing."""
    comps = compounds(export)
    out = []
    claims = {}
    for kw in sorted(comps):
        c = comps[kw]
        own = [c.get("name") or kw] + list(c.get("aliases") or [])
        for name in own:
            if name != kw:
                claims.setdefault(("export", name), set()).add(kw)
        for name in c.get("published_names") or []:
            claims.setdefault(("published", name), set()).add(kw)
    for (kind, name), kws in sorted(claims.items()):
        if len(kws) > 1:
            out.append("%s is named %r by %s" % (
                "more than one compound" if kind == "export" else "more than one published name",
                name, ", ".join(sorted(kws))))
        other = [k for k in kws if k != name]
        if name in comps and other:
            out.append("%r is the keyword of %s and also a name of %s" % (
                name, name, ", ".join(sorted(other))))
    for kw in sorted(comps):
        c = comps[kw]
        native = c.get("analog_of") or ""
        if c.get("role") in LABELLED_ROLES and native:
            target = comps.get(native)
            if target is None or target.get("role") != "analyte":
                out.append("%s is the labelled form of %r, which is not a native "
                           "analyte in the library" % (kw, native))
    return out


def referenced(profile):
    """The compound names a method profile uses: its analyte panel, its
    surrogate links (both sides) and its labelled standards with the
    standards they are linked to. (Published-method designations, such as
    EPA 1633A's EIS table, and isomer peak names are not compounds.)"""
    p = profile or {}
    out = list(p.get("master_analyte_set") or [])
    sm = p.get("surrogate_map") or []
    if isinstance(sm, dict):
        pairs = list(sm.items())
    else:
        pairs = [(r.get("analyte"), r.get("surrogate_is")) for r in sm if isinstance(r, dict)]
    for analyte, surrogate in pairs:
        out += [analyte, surrogate]
    grid = p.get("labelled_standards")
    if isinstance(grid, dict):
        for kw, entry in grid.items():
            out.append(kw)
            if isinstance(entry, dict):
                out.append(entry.get("reference"))
    seen = []
    for name in out:
        name = _text(name)
        if name and name not in seen:
            seen.append(name)
    return seen


def missing(export, profile):
    """The names `profile` uses that resolve to no compound in the library."""
    comps = compounds(export)
    n2k = name_to_keyword(export)
    return [n for n in referenced(profile) if n2k.get(n, n) not in comps]


# ── accessors (all from the export) ─────────────────────────────────────────

def name_to_keyword(export):
    """{name: keyword} for every display name that differs from its keyword
    and every alias. A keyword is not in it: it resolves to itself."""
    out = {}
    for kw in sorted(compounds(export)):
        c = compounds(export)[kw]
        name = c.get("name") or kw
        if name != kw:
            out[name] = kw
        for alias in c.get("aliases") or []:
            if alias != kw:
                out[alias] = kw
    return out


def synonyms(export):
    """{published-method name: keyword}."""
    out = {}
    for kw in sorted(compounds(export)):
        for name in compounds(export)[kw].get("published_names") or []:
            out[name] = kw
    return out


def native_keyword_for(export, published_name, n2k=None):
    """A compound's keyword from a published method's spelling of it, else
    from an export name; the name unchanged when the library does not know it."""
    if not published_name:
        return published_name
    syn = synonyms(export)
    if published_name in syn:
        return syn[published_name]
    if n2k is None:
        n2k = name_to_keyword(export)
    return n2k.get(published_name, published_name)


def _by(export, roles):
    return dict((kw, c) for kw, c in compounds(export).items() if c.get("role") in roles)


def labelled_keywords(export):
    return set(_by(export, LABELLED_ROLES))


def labelled_names(export):
    """{keyword: display name} of the labelled standards."""
    return dict((kw, c.get("name") or kw) for kw, c in _by(export, LABELLED_ROLES).items())


def native_names(export):
    """{keyword: display name} of the native analytes."""
    return dict((kw, c.get("name") or kw) for kw, c in _by(export, ("analyte",)).items())


def names_by_role(export, role):
    """Display names of the compounds with `role`."""
    return set(c.get("name") or kw for kw, c in _by(export, (role,)).items())


def analog_map(export):
    """{labelled keyword: the native keyword it is the labelled form of}."""
    return dict((kw, c["analog_of"]) for kw, c in _by(export, LABELLED_ROLES).items()
                if c.get("analog_of"))


def key_keywords(export):
    return frozenset(kw for kw, c in _by(export, ("analyte",)).items() if c.get("key"))


def key_names(export):
    return frozenset(c.get("name") or kw for kw, c in _by(export, ("analyte",)).items()
                     if c.get("key"))


def cas_by_keyword(export, dashed=True):
    """{native keyword: CAS}. dashed=False strips everything but digits (EDD
    exports want '335671'); an empty or PLACEHOLDER value is returned as it
    stands."""
    out = {}
    for kw, c in _by(export, ("analyte",)).items():
        cas = c.get("cas") or ""
        if not dashed and cas and cas != "PLACEHOLDER":
            cas = re.sub(r"[^0-9]", "", cas)
        out[kw] = cas
    return out


# ── the install seed ────────────────────────────────────────────────────────

def _seed_tables():
    try:
        from senaite.pfas import analyte_reference
        return analyte_reference
    except ImportError:                        # tests and tools on the host
        import analyte_reference
        return analyte_reference


def seed_rows(tables=None):
    """One row per compound of the shipped tables (analyte_reference.py),
    as the migration writes them onto the services: the role the install
    stamps, the display name, CAS, labelled-form link, the export spellings
    (linear-peak names, retired supplier codes, vendor spellings), the
    published-method names and the key-analyte flag. Never read by the
    worker."""
    ar = tables or _seed_tables()
    aliases, published = {}, {}
    for table in (ar.LINEAR_PEAK_ALIASES, ar.LABELLED_KEYWORD_RENAMES,
                  ar.INSTRUMENT_NAME_ALIASES):
        for name in sorted(table):
            aliases.setdefault(table[name], []).append(name)
    for name in sorted(ar.NATIVE_NAME_SYNONYMS):
        published.setdefault(ar.NATIVE_NAME_SYNONYMS[name], []).append(name)
    rows = []
    for r in ar.NATIVE_ANALYTES:
        rows.append({"keyword": r[0], "role": "analyte", "name": r[1], "cas": r[2] or "",
                     "analog_of": "", "aliases": aliases.get(r[0], []),
                     "published_names": published.get(r[0], []), "key": bool(r[8])})
    for r in ar.INTERNAL_STANDARDS:
        rows.append({"keyword": r[0], "role": r[3], "name": r[1], "cas": "",
                     "analog_of": r[2] or "", "aliases": aliases.get(r[0], []),
                     "published_names": published.get(r[0], []), "key": False})
    return rows
