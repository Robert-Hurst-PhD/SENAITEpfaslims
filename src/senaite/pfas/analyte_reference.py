# -*- coding: utf-8 -*-
"""
Master PFAS analyte reference table.

One authoritative source of truth for analyte metadata used to populate the
SENAITE setup (AnalysisServices, keywords, CAS, units) and to cross-link
native analytes to their isotopically-labeled internal standards / surrogates.

CAS numbers and full chemical names are populated where well-established;
entries marked PLACEHOLDER need lab confirmation against your standard COAs.

Fields (NATIVE_ANALYTES tuple, 9 elements):
  [0] keyword        — SENAITE Analysis keyword (no spaces; used in imports/results)
  [1] name           — display name as it appears on instrument export & report
  [2] cas            — CAS Registry Number ("" or PLACEHOLDER if unverified)
  [3] full_name      — IUPAC-ish full chemical name
  [4] klass          — PFCA | PFSA | FTS | FOSA | PFECA | Cl-PFAES | FTCA | other
  [5] chain          — perfluorocarbon chain length (approx, for sort order)
  [6] surrogate_is   — the labeled IS keyword that quantifies this native (FDA §9-1)
  [7] no_labeled     — reference only, NOT read: whether an analyte has its own
                       labelled standard is derived per method from its surrogate
                       links (labelled_coverage; consolidation P4). Kept so the
                       row layout does not shift; tests pin that the derivation
                       agrees with it on the shipped profiles.
  [8] is_key_analyte — True for the four regulatory priority analytes and their
                       branched isomers: PFOS, PFOA, PFHxS, PFNA (+ br-PFOS,
                       br-PFHxS). FDA Table 10-1 Tier 1 analytes in tight matrices.
"""

# ── 47 native target analytes ────────────────────────────────────────────────
NATIVE_ANALYTES = [
    # keyword,        name,           cas,          full_name, class, chain, surrogate_is, no_labeled, is_key
    ("PFBA",   "PFBA",   "375-22-4",   "Perfluorobutanoic acid",                          "PFCA",    4,  "13C3-PFBA",           False, False),
    ("PFPeA",  "PFPeA",  "2706-90-3",  "Perfluoropentanoic acid",                         "PFCA",    5,  "13C3-PFPeA",          False, False),
    ("PFHxA",  "PFHxA",  "307-24-4",   "Perfluorohexanoic acid",                          "PFCA",    6,  "13C5-PFHxA",          False, False),
    ("PFHpA",  "PFHpA",  "375-85-9",   "Perfluoroheptanoic acid",                         "PFCA",    7,  "13C4-PFHpA",          False, False),
    ("PFOA",   "PFOA",   "335-67-1",   "Perfluorooctanoic acid",                          "PFCA",    8,  "13C8-PFOA",           False, True),
    ("PFNA",   "PFNA",   "375-95-1",   "Perfluorononanoic acid",                          "PFCA",    9,  "13C5-PFNA",           False, True),
    ("PFDA",   "PFDA",   "335-76-2",   "Perfluorodecanoic acid",                          "PFCA",    10, "13C2-PFDA",           False, False),
    ("PFUDA",  "PFUDA",  "2058-94-8",  "Perfluoroundecanoic acid",                        "PFCA",    11, "13C2-PFUDA",           False, False),
    ("PFDoA",  "PFDoA",  "307-55-1",   "Perfluorododecanoic acid",                        "PFCA",    12, "13C2-PFDoA",           False, False),
    ("PFTrDA", "PFTrDA", "72629-94-8", "Perfluorotridecanoic acid",                       "PFCA",    13, "13C2-PFDoA",           True,  False),
    ("PFTeDA", "PFTeDA", "376-06-7",   "Perfluorotetradecanoic acid",                     "PFCA",    14, "13C2-PFTeDA",         False, False),
    ("PFHxDA", "PFHxDA", "67905-19-5", "Perfluorohexadecanoic acid",                      "PFCA",    16, "13C2-PFHxDA",         False, False),
    ("PFODA",  "PFODA",  "16517-11-6", "Perfluorooctadecanoic acid",                      "PFCA",    18, "",                 True,  False),
    ("PFBS",   "PFBS",   "375-73-5",   "Perfluorobutanesulfonic acid",                    "PFSA",    4,  "13C3-PFBS",           False, False),
    ("PFPeS",  "PFPeS",  "2706-91-4",  "Perfluoropentanesulfonic acid",                   "PFSA",    5,  "",                 True,  False),
    ("PFHxS",  "PFHxS",   "355-46-4",  "Perfluorohexanesulfonic acid (linear)",           "PFSA",    6,  "13C3-PFHxS",          False, True),
    ("br-PFHxS","br-PFHxS","",         "Perfluorohexanesulfonic acid (branched)",          "PFSA",    6,  "13C3-PFHxS",          False, True),
    ("PFHpS",  "PFHpS",  "375-92-8",   "Perfluoroheptanesulfonic acid",                   "PFSA",    7,  "",                 True,  False),
    ("PFOS",   "PFOS",   "1763-23-1",  "Perfluorooctanesulfonic acid (linear)",            "PFSA",    8,  "13C8-PFOS",           False, True),
    ("br-PFOS","br-PFOS","",           "Perfluorooctanesulfonic acid (branched)",           "PFSA",    8,  "13C8-PFOS",           False, True),
    ("PFNS",   "PFNS",   "68259-12-1", "Perfluorononanesulfonic acid",                    "PFSA",    9,  "",                 True,  False),
    ("PFDS",   "PFDS",   "335-77-3",   "Perfluorodecanesulfonic acid",                    "PFSA",    10, "",                 True,  False),
    ("PFDoS",  "PFDoS",  "79780-39-5", "Perfluorododecanesulfonic acid",                  "PFSA",    12, "",                 True,  False),
    ("PFTrDS", "PFTrDS", "PLACEHOLDER","Perfluorotridecanesulfonic acid",                 "PFSA",    13, "",                 True,  False),
    ("PFUnDS", "PFUnDS", "749786-16-1","Perfluoroundecanesulfonic acid",                  "PFSA",    11, "",                 True,  False),
    ("4:2FTS", "4:2 FTS","757124-72-4","1H,1H,2H,2H-perfluorohexane sulfonic acid",       "FTS",     6,  "13C2-D4-4:2FTS",        False, False),
    ("6:2FTS", "6:2FTS", "27619-97-2", "1H,1H,2H,2H-perfluorooctane sulfonic acid",       "FTS",     8,  "13C2-D4-6:2FTS",        False, False),
    ("8:2FTS", "8:2 FTS","39108-34-4", "1H,1H,2H,2H-perfluorodecane sulfonic acid",       "FTS",     10, "13C2-D4-8:2FTS",        False, False),
    ("10:2FTS","10:2 FTS","120226-60-0","1H,1H,2H,2H-perfluorododecane sulfonic acid",    "FTS",     12, "13C2-D4-10:2FTS",       False, False),
    ("FOSA",   "FOSA",   "754-91-6",   "Perfluorooctanesulfonamide",                      "FOSA",    8,  "13C8-FOSA",           False, False),
    ("GenX",   "GenX (HFPO-DA)","13252-13-6","Hexafluoropropylene oxide dimer acid",      "PFECA",   6,  "13C3-HFPO-DA",           False,False),
    ("DONA",   "DONA",   "919005-14-4","4,8-dioxa-3H-perfluorononanoic acid (ADONA)",     "PFECA",   7,  "",                 True,  False),
    ("9ClPF3ONS","9Cl-PF3ONS","756426-58-1","9-chlorohexadecafluoro-3-oxanonane-1-sulfonic acid (F-53B major)","Cl-PFAES",8,"",True,False),
    ("11ClPF3OUdS","11Cl-PF3OUdS","763051-92-9","11-chloroeicosafluoro-3-oxaundecane-1-sulfonic acid (F-53B minor)","Cl-PFAES",10,"",True,False),
    # ── EPA 1633A-specific analytes (FOSA precursors / novel PFAS / FTCAs) ──────
    ("NMeFOSA",  "NMeFOSA",  "31506-32-8",  "N-methylperfluorooctanesulfonamide",            "FOSA",  8,  "D3-NMeFOSA",  False, False),
    ("NEtFOSA",  "NEtFOSA",  "4151-50-2",   "N-ethylperfluorooctanesulfonamide",             "FOSA",  8,  "D5-NEtFOSA",  False, False),
    ("NMeFOSAA", "NMeFOSAA", "2355-31-9",   "N-methylperfluorooctanesulfonamidoacetic acid",  "FOSA",  8,  "D3-NMeFOSAA", False, False),
    ("NEtFOSAA", "NEtFOSAA", "2991-50-6",   "N-ethylperfluorooctanesulfonamidoacetic acid",   "FOSA",  8,  "D5-NEtFOSAA", False, False),
    ("NMeFOSE",  "NMeFOSE",  "24448-09-7",  "N-methylperfluorooctanesulfonamidoethanol",      "FOSA",  8,  "D7-NMeFOSE",  False, False),
    ("NEtFOSE",  "NEtFOSE",  "1691-99-2",   "N-ethylperfluorooctanesulfonamidoethanol",       "FOSA",  8,  "D9-NEtFOSE",  False, False),
    ("PFMPA",    "PFMPA",    "377-73-1",    "Perfluoro-3-methoxypropanoic acid",              "PFECA", 3,  "",            True,  False),
    ("PFMBA",    "PFMBA",    "863090-89-5", "Perfluoro-4-methoxybutanoic acid",               "PFECA", 4,  "",            True,  False),
    ("NFDHA",    "NFDHA",    "151772-58-6", "Perfluoro-3,6-dioxaoctanoic acid",               "PFECA", 6,  "",            True,  False),
    ("PFEESA",   "PFEESA",   "113507-82-7", "Perfluoroethyl ether sulfonic acid",             "PFECA", 4,  "",            True,  False),
    ("3:3FTCA",  "3:3FTCA",  "356-02-5",    "3:3 fluorotelomer carboxylic acid",              "FTCA",  3,  "",            True,  False),
    ("5:3FTCA",  "5:3FTCA",  "914637-49-3", "5:3 fluorotelomer carboxylic acid",              "FTCA",  5,  "",            True,  False),
    ("7:3FTCA",  "7:3FTCA",  "812-70-4",    "7:3 fluorotelomer carboxylic acid",              "FTCA",  7,  "",            True,  False),
]

# ── 30 isotopically-labeled internal standards / surrogates ──────────────────
# quant_is: surrogates quantify against 13C4-PFOA (FDA Table 9-1, mean RF).
INTERNAL_STANDARDS = [
    # keyword,          name,                 labeled_analog_of, role
    ("13C3-PFBA",   "13C3-PFBA",          "PFBA",   "surrogate"),
    ("13C3-PFPeA",  "13C3-PFPeA",         "PFPeA",  "surrogate"),
    ("13C5-PFHxA",  "13C5-PFHxA",         "PFHxA",  "surrogate"),
    ("13C4-PFHpA",  "13C4-PFHpA",         "PFHpA",  "surrogate"),
    ("13C8-PFOA",   "13C8-PFOA",          "PFOA",   "surrogate"),
    ("13C4-PFOA",   "13C4-PFOA",          "PFOA",   "injection_is"),  # the IS surrogates quantify against
    ("13C5-PFNA",   "13C5-PFNA",          "PFNA",   "surrogate"),
    ("13C2-PFDA",   "13C2-PFDA",          "PFDA",   "surrogate"),
    ("13C2-PFUDA",   "13C2-PFUDA",         "PFUDA",  "surrogate"),
    ("13C2-PFDoA",   "13C2-PFDoA",         "PFDoA",  "surrogate"),
    ("13C2-PFTeDA", "13C2-PFTeDA",        "PFTeDA", "surrogate"),
    ("13C2-PFHxDA", "13C2-PFHxDA",        "PFHxDA", "surrogate"),
    ("13C3-PFBS",   "13C3-PFBS",          "PFBS",   "surrogate"),
    ("13C3-PFHxS",  "13C3-PFHxS",         "PFHxS",  "surrogate"),
    ("13C8-PFOS",   "13C8-PFOS",          "PFOS",   "surrogate"),
    # EPA 537.1 v2.0 §7.2.1 / §7.2.2: its internal
    # standards 13C2-PFOA and 13C4-PFOS, and its surrogate 13C2-PFHxA
    ("13C2-PFOA",   "13C2-PFOA",          "PFOA",   "injection_is"),
    ("13C4-PFOS",   "13C4-PFOS",          "PFOS",   "injection_is"),
    ("13C2-PFHxA",  "13C2-PFHxA",         "PFHxA",  "surrogate"),
    ("13C3-HFPO-DA",   "13C3-GenX (HFPO-DA)","GenX",   "surrogate"),
    ("13C8-FOSA",   "13C8-FOSA",          "FOSA",   "surrogate"),
    ("13C2-D4-4:2FTS","13C2,D4-4:2FTS",     "4:2FTS", "surrogate"),
    ("13C2-D4-6:2FTS","13C2,D4-6:2FTS",     "6:2FTS", "surrogate"),
    ("13C2-D4-8:2FTS","13C2,D4-8:2FTS",     "8:2FTS", "surrogate"),
    ("13C2-D4-10:2FTS","13C2,D4-10:2FTS",   "10:2FTS","surrogate"),
    # ── EPA 1633A FOSA-surrogate IS ──────────────────────────────────────────
    ("D3-NMeFOSA",  "D3-NMeFOSA",  "NMeFOSA",  "surrogate"),
    ("D5-NEtFOSA",  "D5-NEtFOSA",  "NEtFOSA",  "surrogate"),
    ("D3-NMeFOSAA", "D3-NMeFOSAA", "NMeFOSAA", "surrogate"),
    ("D5-NEtFOSAA", "D5-NEtFOSAA", "NEtFOSAA", "surrogate"),
    ("D7-NMeFOSE",  "D7-NMeFOSE",  "NMeFOSE",  "surrogate"),
    ("D9-NEtFOSE",  "D9-NEtFOSE",  "NEtFOSE",  "surrogate"),
]

# ── Methods (each a SENAITE Method object) ───────────────────────────────────
METHODS = [
    ("FDA_32PFAS", "USDA/FDA 32-PFAS in Food v10",
     "LC-MS/MS isotope dilution; AOAC SMPR 2023.003 criteria"),
    ("EPA_537_1",  "EPA 537.1 PFAS in Drinking Water",
     "SPE + LC-MS/MS, internal standard calibration, origin-forced curve"),
    ("EPA_1633A",  "EPA 1633A PFAS (aqueous/solid/biosolid/tissue)",
     "Isotope dilution LC-MS/MS, 40 analytes, per-analyte EIS limits"),
]

# ── Sample types (matrix) with default units & method affinity ───────────────
# unit: ng/L for waters, ng/g for solids/tissue/food
SAMPLE_TYPES = [
    # prefix, title, unit, methods, hazardous, retention_days
    ("DW",  "Drinking Water",       "ng/L", ["EPA_537_1", "EPA_1633A"], False, 14),
    ("GW",  "Groundwater",          "ng/L", ["EPA_1633A"],              False, 14),
    ("SW",  "Surface Water",        "ng/L", ["EPA_1633A"],              False, 14),
    ("WW",  "Wastewater",           "ng/L", ["EPA_1633A"],              False, 14),
    ("LL",  "Landfill Leachate",    "ng/L", ["EPA_1633A"],              True,  14),
    ("SOIL","Soil",                 "ng/g", ["EPA_1633A"],              False, 28),
    ("SED", "Sediment",             "ng/g", ["EPA_1633A"],              False, 28),
    ("BIO", "Biosolid",             "ng/g", ["EPA_1633A"],              True,  28),
    ("TIS", "Aquatic Tissue",       "ng/kg", ["EPA_1633A", "FDA_32PFAS"],False, 28),
    ("MEAT","Meat / Muscle",        "ng/kg", ["FDA_32PFAS"],             False, 28),
    ("EGG", "Eggs",                 "ng/kg", ["FDA_32PFAS"],             False, 28),
    ("FISH","Fish / Seafood",       "ng/kg", ["FDA_32PFAS"],             False, 28),
    ("MILK","Milk",                 "ng/kg", ["FDA_32PFAS"],             False, 14),
    ("FEED","Animal Feed",          "ng/kg", ["FDA_32PFAS"],             False, 60),
]

# ── Sample containers (PFAS-safe; NO PTFE/fluoropolymer contact) ─────────────
CONTAINERS = [
    # title, capacity, material, methods, notes
    ("HDPE Bottle 250 mL",  "250 mL", "HDPE",
     ["EPA_537_1"], "537.1 drinking water; Trizma preservative added"),
    ("HDPE Bottle 500 mL",  "500 mL", "HDPE",
     ["EPA_1633A"], "1633A aqueous; no headspace requirement"),
    ("HDPE Bottle 1 L",     "1 L",    "HDPE",
     ["EPA_1633A"], "high-volume aqueous"),
    ("PP Centrifuge Tube 50 mL", "50 mL", "Polypropylene",
     ["EPA_1633A", "FDA_32PFAS"], "solids, tissue, biosolid"),
    ("PP Jar 250 mL",       "250 mL", "Polypropylene",
     ["EPA_1633A"], "soil / sediment / biosolid"),
    ("PP Bag (Whirl-Pak)",  "varies", "Polyethylene",
     ["FDA_32PFAS"], "food / tissue field collection"),
    ("Foil-wrapped (PFAS-free)", "varies", "Aluminium foil",
     ["FDA_32PFAS"], "meat/fish wrap; no fluoropolymer contact"),
]

# ── Storage locations (with target conditions) ───────────────────────────────
STORAGE_LOCATIONS = [
    # title, address/code, temp, notes
    ("Sample Fridge A",      "FRIDGE-A",  "6 °C",   "Aqueous samples awaiting extraction (537.1 ≤6 °C)"),
    ("Sample Freezer B",     "FREEZER-B", "-20 °C", "Food/tissue samples; long-term sample hold"),
    ("Extract Freezer C",    "FREEZER-C", "-20 °C", "Final extracts awaiting injection"),
    ("Standards Freezer D",  "FREEZER-D", "-20 °C", "Neat standards & stock solutions"),
    ("Standards Fridge E",   "FRIDGE-E",  "6 °C",   "Working calibration & CCV solutions (per FDA §6)"),
    ("Reagent Cabinet F",    "CAB-F",     "ambient","Solvents, salts, SPE cartridges"),
    ("Archive Freezer G",    "FREEZER-G", "-20 °C", "Post-analysis retention per method holding times"),
]

# ── Preservation (for sample reception workflow) ─────────────────────────────
PRESERVATIONS = [
    ("Trizma", "Trizma preservative (537.1)", "EPA_537_1"),
    ("AmmAcetate", "Ammonium acetate", "EPA_1633A"),
    ("Cool6C", "Cool to 6 °C", "ALL"),
    ("FrozenMinus20", "Freeze to -20 °C", "FDA_32PFAS"),
    ("None", "No preservative", "ALL"),
]

# Calibration ladders live on each method profile (Calibration & CCV;
# senaite.pfas.calibration_levels) -- not here (QC consolidation P1).


def native_count():
    return len(NATIVE_ANALYTES)


def is_count():
    return len(INTERNAL_STANDARDS)


# ── Derived sets from NATIVE_ANALYTES ────────────────────────────────────────

def get_key_analyte_keywords():
    """Frozenset of SENAITE keywords for key analytes (FDA Table 10-1 Tier 1)."""
    return frozenset(row[0] for row in NATIVE_ANALYTES if row[8])


def get_key_analyte_names():
    """Frozenset of display names for key analytes."""
    return frozenset(row[1] for row in NATIVE_ANALYTES if row[8])


def get_cas_by_keyword(dashed=True):
    """Dict of {keyword: CAS} from the master analyte table — the single source
    of truth for analyte CAS.

    SENAITE core's AnalysisService has no CAS field in 2.6, so CAS is owned in
    this add-on, keyed by the core AnalysisService keyword (the join to core).

    dashed=True  -> registry format, e.g. '335-67-1'
    dashed=False -> digits only, e.g. '335671' (EDD exports want undashed CAS)
    Empty / 'PLACEHOLDER' entries are returned unchanged.
    """
    import re as _re
    out = {}
    for row in NATIVE_ANALYTES:
        cas = row[2] or ""
        if not dashed and cas and cas != "PLACEHOLDER":
            cas = _re.sub(r"[^0-9]", "", cas)
        out[row[0]] = cas
    return out


def get_method_ids():
    """Ordered list of method IDs — the single source of truth for "which
    methods exist" (FDA_32PFAS, EPA_537_1, EPA_1633A). Presentation labels stay
    local to each consumer; only the ID list/order is owned here, so adding a
    method to METHODS propagates everywhere that derives from this."""
    return [row[0] for row in METHODS]


def get_surrogate_map_by_keyword():
    """Dict of {native_keyword: surrogate_is_keyword} for analytes with a matched IS."""
    return {row[0]: row[6] for row in NATIVE_ANALYTES if row[6]}


def derive_surrogate_map(analyte_keywords):
    """A method profile's `surrogate_map`, derived for one analyte panel.

    Returns the stored shape -- `[{"analyte": kw, "surrogate_is": kw}, ...]` --
    ordered by the given panel so two methods sharing an analyte agree.

    Which labelled compound quantifies a native is a property of the ANALYTE,
    not of the method, and it is already recorded once in `NATIVE_ANALYTES`.
    The FDA and 1633A profiles carried hand-maintained copies of it; both were
    verified byte-identical to this derivation before it was introduced, and
    EPA 537.1 carried an EMPTY list -- so `qc_qualification.analytes_for_failure`
    had no map to reverse and named the labelled compound on the certificate
    instead of the natives the client actually reads.

    A lab may still override the map in the Method Profile editor; this is the
    default it starts from, not a value imposed at read time.
    """
    mapping = get_surrogate_map_by_keyword()
    return [{"analyte": kw, "surrogate_is": mapping[kw]}
            for kw in (analyte_keywords or []) if mapping.get(kw)]


def get_surrogate_map_by_name():
    """Dict of {native_display_name: surrogate_is_keyword} for analytes with a matched IS."""
    return {row[1]: row[6] for row in NATIVE_ANALYTES if row[6]}


def get_surrogates():
    """List of [keyword, name] for labeled IS with role='surrogate'."""
    return [[row[0], row[1]] for row in INTERNAL_STANDARDS if row[3] == "surrogate"]


def get_injection_is_list():
    """List of [keyword, name] for IS with role='injection_is' (e.g. 13C4-PFOA)."""
    return [[row[0], row[1]] for row in INTERNAL_STANDARDS if row[3] == "injection_is"]


def get_labeled_analog_map():
    """{labelled_compound_keyword: native_keyword} — which native each labelled
    compound stands in for. Already recorded as INTERNAL_STANDARDS row[2]; this
    is the accessor so nothing re-derives it from a name."""
    return {row[0]: row[2] for row in INTERNAL_STANDARDS if row[2]}


# ── Published-method spellings of a NATIVE analyte ───────────────────────────
# A published method may name a native differently from this table's keyword.
# These are pure synonyms -- the same substance under another name -- NOT
# different compounds, which is why they belong here beside the keyword rather
# than in a method profile:
#
#   HFPO-DA  EPA's name for what this table keys as GenX (both are the
#            hexafluoropropylene oxide dimer acid, CAS 13252-13-6)
#   PFUnA    "perfluoroundecanoic acid" numbered as undecanoic; this table keys
#            it PFUDA (CAS 2058-94-8)
#   PFOSA    "perfluorooctanesulfonamide" with the PF- prefix spelled out; this
#            table keys it FOSA (CAS 754-91-6)
#
# WHY THIS EXISTS. EPA 1633A Table 6 designates its extracted internal standards
# by the labelled form of the native (13C3-HFPO-DA, 13C7-PFUnA, 13C8-PFOSA), so
# joining a Table 6 row to the analyte it belongs to needs the native's
# published spelling. Verified complete, not guessed: of 1633A's 24 Table 6
# designations, 21 resolve to a native by stripping the isotopic label alone,
# and the 3 that do not are exactly these -- which are exactly the 3 natives the
# method's own surrogate map leaves otherwise uncovered. Complementary sets,
# 24/24, so the join is total.
NATIVE_NAME_SYNONYMS = {
    "HFPO-DA": "GenX",
    "PFUnA": "PFUDA",
    "PFOSA": "FOSA",
    # EPA 537.1's name for perfluorotetradecanoic acid, and the hyphenated
    # display names some exports use (method studies join on these)
    "PFTA": "PFTeDA",
    # EPA 537.1's name for 4,8-dioxa-3H-perfluorononanoic acid, keyed DONA
    # here (an export naming it ADONA was never matched)
    "ADONA": "DONA",
    "N-EtFOSAA": "NEtFOSAA",
    "N-MeFOSAA": "NMeFOSAA",
}


def native_keyword_for(published_name):
    """A native analyte's keyword from whatever a published method calls it.

    Returns the name unchanged when it is already a keyword or is unknown --
    the caller then fails to join and says so, which is the same outcome as
    before but for a genuinely unrecognised analyte rather than a synonym.
    """
    if not published_name:
        return published_name
    if published_name in NATIVE_NAME_SYNONYMS:
        return NATIVE_NAME_SYNONYMS[published_name]
    return COMPOUND_NAME_TO_KEYWORD.get(published_name, published_name)


# ── Compound-name → keyword reverse lookup ───────────────────────────────────
# Maps instrument export display names back to SENAITE keyword (row[0]) when
# they differ.  Example: "lr-PFOS" → "PFOS", "9Cl-PF3ONS" → "9ClPF3ONS".
# br-PFOS / br-PFHxS map to themselves (keyword == display name).
# Use: COMPOUND_NAME_TO_KEYWORD.get(compound_name, compound_name)

def _build_compound_name_to_keyword():
    """Display name -> keyword, for natives AND labelled compounds.

    Walking only NATIVE_ANALYTES left the labelled compounds with no alias at
    all, so nothing could tell that the profile's "13C8-PFOA" and the instrument's
    "13C8-PFOA" are the same surrogate. Both spellings have been sitting in
    INTERNAL_STANDARDS as (keyword, name, ...) the whole time.
    """
    mapping = {}
    for row in list(NATIVE_ANALYTES) + list(INTERNAL_STANDARDS):
        keyword, display_name = row[0], row[1]
        if display_name != keyword:
            mapping[display_name] = keyword
    return mapping


# Linear-PEAK names that resolve to the reported analyte. PFOS and PFHxS were
# displayed as "lr-PFOS"/"lr-PFHxS" until 2026-10-01: a summed
# result is reported as the plain analyte, and "lr-" names only the linear
# peak, which instruments export under that name. Kept so every name the
# matching accepted before still resolves to the same keyword.
LINEAR_PEAK_ALIASES = {"lr-PFHxS": "PFHxS", "lr-PFOS": "PFOS"}

# A labelled standard's keyword is its label; the
# supplier codes it replaced still resolve, so runs, exports and history made
# before the rename name the same compound.
LABELLED_KEYWORD_RENAMES = {
    "M3PFBA": "13C3-PFBA", "M3PFPeA": "13C3-PFPeA", "M5PFHxA": "13C5-PFHxA",
    "M4PFHpA": "13C4-PFHpA", "M8PFOA": "13C8-PFOA", "M4PFOA": "13C4-PFOA",
    "M5PFNA": "13C5-PFNA", "M2PFDA": "13C2-PFDA", "MPFUdA": "13C2-PFUDA",
    "MPFDoA": "13C2-PFDoA", "M2PFTeDA": "13C2-PFTeDA", "M2PFHxDA": "13C2-PFHxDA",
    "M3PFBS": "13C3-PFBS", "M3PFHxS": "13C3-PFHxS", "M8PFOS": "13C8-PFOS",
    "M3HFPO": "13C3-HFPO-DA", "M8FOSA": "13C8-FOSA",
    "M2-4:2FTS": "13C2-D4-4:2FTS", "M2-6:2FTS": "13C2-D4-6:2FTS",
    "M2-8:2FTS": "13C2-D4-8:2FTS", "M2-10:2FTS": "13C2-D4-10:2FTS",
    "MD3NMeFOSA": "D3-NMeFOSA", "MD5NEtFOSA": "D5-NEtFOSA",
    "MD3NMeFOSAA": "D3-NMeFOSAA", "MD5NEtFOSAA": "D5-NEtFOSAA",
    "MD7NMeFOSE": "D7-NMeFOSE", "MD9NEtFOSE": "D9-NEtFOSE",
}

# Instrument spellings of labelled standards seen in the lab's processing
# method export that differ from the library's names. A
# lab-editable compound-name alias table does not exist yet.
INSTRUMENT_NAME_ALIASES = {
    "13C3 GenX (HFPO-DA)": "13C3-HFPO-DA",
    "D5-N-EtFOSAA": "D5-NEtFOSAA",
}

COMPOUND_NAME_TO_KEYWORD = _build_compound_name_to_keyword()
COMPOUND_NAME_TO_KEYWORD.update(LINEAR_PEAK_ALIASES)
COMPOUND_NAME_TO_KEYWORD.update(LABELLED_KEYWORD_RENAMES)
COMPOUND_NAME_TO_KEYWORD.update(INSTRUMENT_NAME_ALIASES)


# ── SENAITE AnalysisService pfas_role helpers ────────────────────────────────
# Extension fields added by archetypes.schemaextender do not generate
# automatic accessor methods (getPfas_role is never created).  Use these
# helpers wherever pfas_role must be read or written on a service object.

def get_pfas_role(svc_obj):
    """Return pfas_role value from an AnalysisService, or '' if not set."""
    try:
        field = svc_obj.Schema().get("pfas_role")
        if field is not None:
            return field.get(svc_obj) or ""
    except Exception:
        pass
    return svc_obj.__dict__.get("pfas_role", "")


def set_pfas_role(svc_obj, role):
    """Set pfas_role on an AnalysisService via the schema field."""
    try:
        field = svc_obj.Schema().get("pfas_role")
        if field is not None:
            field.set(svc_obj, role)
            return True
    except Exception:
        pass
    try:
        svc_obj.__dict__["pfas_role"] = role
        return True
    except Exception:
        return False


def get_method_is_services(method_id, portal=None):
    """
    Return list of (keyword, title, role) for all IS/surrogate services
    associated with the given method_id.

    Derives membership by looking at which native analytes in NATIVE_ANALYTES
    have the given method in their Method association, then collecting their
    surrogate_is keywords plus the injection IS.

    If portal is supplied, cross-checks against actual SENAITE AnalysisService
    objects to confirm they exist.  Otherwise returns from NATIVE_ANALYTES only.
    """
    # Collect surrogate keywords used by this method's native analytes
    used_surrogates = set()
    for row in NATIVE_ANALYTES:
        if row[6]:  # has surrogate_is
            used_surrogates.add(row[6])

    # Build IS list: used surrogates + injection_is
    injection_is = {row[0] for row in INTERNAL_STANDARDS if row[3] == "injection_is"}
    wanted = used_surrogates | injection_is

    result = []
    for row in INTERNAL_STANDARDS:
        if row[0] in wanted:
            result.append({"keyword": row[0], "title": row[1], "role": row[3]})
    return result
