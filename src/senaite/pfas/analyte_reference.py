# -*- coding: utf-8 -*-
"""
Master PFAS analyte reference table.

One authoritative source of truth for analyte metadata used to populate the
SENAITE setup (AnalysisServices, keywords, CAS, units) and to cross-link
native analytes to their isotopically-labeled internal standards / surrogates.

CAS numbers and full chemical names are populated where well-established;
entries marked PLACEHOLDER need lab confirmation against your standard COAs.

Fields:
  keyword       — SENAITE Analysis keyword (no spaces; used in imports/results)
  name          — display name as it appears on instrument export & report
  cas           — CAS Registry Number ("" or PLACEHOLDER if unverified)
  full_name     — IUPAC-ish full chemical name
  klass         — PFCA | PFSA | FTS | FOSA | PFECA | Cl-PFAES | other
  chain         — perfluorocarbon chain length (approx, for sort order)
  is_native     — True for target analytes, False for IS/surrogates
  surrogate_is  — for natives: the labeled surrogate used as its IS (FDA 9-1)
  quant_is      — for surrogates: the injection IS they quantify against
  no_labeled    — True if no commercially matched labeled standard (N.C. tier)
"""

# ── 34 native target analytes ────────────────────────────────────────────────
NATIVE_ANALYTES = [
    # keyword,        name,           cas,          full_name, class, chain, surrogate_is, no_labeled
    ("PFBA",   "PFBA",   "375-22-4",  "Perfluorobutanoic acid",            "PFCA", 4,  "M3PFBA",  False),
    ("PFPeA",  "PFPeA",  "2706-90-3", "Perfluoropentanoic acid",           "PFCA", 5,  "M3PFPeA", False),
    ("PFHxA",  "PFHxA",  "307-24-4",  "Perfluorohexanoic acid",            "PFCA", 6,  "M5PFHxA", False),
    ("PFHpA",  "PFHpA",  "375-85-9",  "Perfluoroheptanoic acid",           "PFCA", 7,  "M4PFHpA", False),
    ("PFOA",   "PFOA",   "335-67-1",  "Perfluorooctanoic acid",            "PFCA", 8,  "M8PFOA",  False),
    ("PFNA",   "PFNA",   "375-95-1",  "Perfluorononanoic acid",            "PFCA", 9,  "M5PFNA",  False),
    ("PFDA",   "PFDA",   "335-76-2",  "Perfluorodecanoic acid",            "PFCA", 10, "M2PFDA",  False),
    ("PFUDA",  "PFUDA",  "2058-94-8", "Perfluoroundecanoic acid",          "PFCA", 11, "MPFUdA",  False),
    ("PFDoA",  "PFDoA",  "307-55-1",  "Perfluorododecanoic acid",          "PFCA", 12, "MPFDoA",  False),
    ("PFTrDA", "PFTrDA", "72629-94-8","Perfluorotridecanoic acid",         "PFCA", 13, "MPFDoA",  True),
    ("PFTeDA", "PFTeDA", "376-06-7",  "Perfluorotetradecanoic acid",       "PFCA", 14, "M2PFTeDA",False),
    ("PFHxDA", "PFHxDA", "67905-19-5","Perfluorohexadecanoic acid",        "PFCA", 16, "M2PFHxDA",False),
    ("PFODA",  "PFODA",  "16517-11-6","Perfluorooctadecanoic acid",        "PFCA", 18, "",        True),
    ("PFBS",   "PFBS",   "375-73-5",  "Perfluorobutanesulfonic acid",      "PFSA", 4,  "M3PFBS",  False),
    ("PFPeS",  "PFPeS",  "2706-91-4", "Perfluoropentanesulfonic acid",     "PFSA", 5,  "",        True),
    ("PFHxS",  "lr-PFHxS","355-46-4", "Perfluorohexanesulfonic acid (linear)","PFSA",6,"M3PFHxS", False),
    ("br-PFHxS","br-PFHxS","",        "Perfluorohexanesulfonic acid (branched)","PFSA",6,"M3PFHxS",False),
    ("PFHpS",  "PFHpS",  "375-92-8",  "Perfluoroheptanesulfonic acid",     "PFSA", 7,  "",        True),
    ("PFOS",   "lr-PFOS","1763-23-1", "Perfluorooctanesulfonic acid (linear)","PFSA",8,"M8PFOS",  False),
    ("br-PFOS","br-PFOS","",          "Perfluorooctanesulfonic acid (branched)","PFSA",8,"M8PFOS",False),
    ("PFNS",   "PFNS",   "68259-12-1","Perfluorononanesulfonic acid",      "PFSA", 9,  "",        True),
    ("PFDS",   "PFDS",   "335-77-3",  "Perfluorodecanesulfonic acid",      "PFSA", 10, "",        True),
    ("PFDoS",  "PFDoS",  "79780-39-5","Perfluorododecanesulfonic acid",    "PFSA", 12, "",        True),
    ("PFTrDS", "PFTrDS", "PLACEHOLDER","Perfluorotridecanesulfonic acid",  "PFSA", 13, "",        True),
    ("PFUnDS", "PFUnDS", "749786-16-1","Perfluoroundecanesulfonic acid",   "PFSA", 11, "",        True),
    ("4:2FTS", "4:2 FTS","757124-72-4","1H,1H,2H,2H-perfluorohexane sulfonic acid","FTS",6,"13C2,D4-4:2FTS",False),
    ("6:2FTS", "6:2FTS", "27619-97-2","1H,1H,2H,2H-perfluorooctane sulfonic acid","FTS",8,"13C2,D4-6:2FTS",False),
    ("8:2FTS", "8:2 FTS","39108-34-4","1H,1H,2H,2H-perfluorodecane sulfonic acid","FTS",10,"13C2,D4-8:2FTS",False),
    ("10:2FTS","10:2 FTS","120226-60-0","1H,1H,2H,2H-perfluorododecane sulfonic acid","FTS",12,"13C2,D4-10:2FTS",False),
    ("FOSA",   "FOSA",   "754-91-6",  "Perfluorooctanesulfonamide",        "FOSA", 8,  "13C8-FOSA",False),
    ("GenX",   "GenX (HFPO-DA)","13252-13-6","Hexafluoropropylene oxide dimer acid","PFECA",6,"13C3-GenX (HFPO-DA)",False),
    ("DONA",   "DONA",   "919005-14-4","4,8-dioxa-3H-perfluorononanoic acid (ADONA)","PFECA",7,"",True),
    ("9ClPF3ONS","9Cl-PF3ONS","756426-58-1","9-chlorohexadecafluoro-3-oxanonane-1-sulfonic acid (F-53B major)","Cl-PFAES",8,"",True),
    ("11ClPF3OUdS","11Cl-PF3OUdS","763051-92-9","11-chloroeicosafluoro-3-oxaundecane-1-sulfonic acid (F-53B minor)","Cl-PFAES",10,"",True),
]

# ── 21 isotopically-labeled internal standards / surrogates ──────────────────
# quant_is: surrogates quantify against M4PFOA (FDA Table 9-1, mean RF).
INTERNAL_STANDARDS = [
    # keyword,          name,                 labeled_analog_of, role
    ("M3PFBA",   "13C3-PFBA",          "PFBA",   "surrogate"),
    ("M3PFPeA",  "13C3-PFPeA",         "PFPeA",  "surrogate"),
    ("M5PFHxA",  "13C5-PFHxA",         "PFHxA",  "surrogate"),
    ("M4PFHpA",  "13C4-PFHpA",         "PFHpA",  "surrogate"),
    ("M8PFOA",   "13C8-PFOA",          "PFOA",   "surrogate"),
    ("M4PFOA",   "13C4-PFOA",          "PFOA",   "injection_is"),  # the IS surrogates quantify against
    ("M5PFNA",   "13C5-PFNA",          "PFNA",   "surrogate"),
    ("M2PFDA",   "13C2-PFDA",          "PFDA",   "surrogate"),
    ("MPFUdA",   "13C2-PFUDA",         "PFUDA",  "surrogate"),
    ("MPFDoA",   "13C2-PFDoA",         "PFDoA",  "surrogate"),
    ("M2PFTeDA", "13C2-PFTeDA",        "PFTeDA", "surrogate"),
    ("M2PFHxDA", "13C2-PFHxDA",        "PFHxDA", "surrogate"),
    ("M3PFBS",   "13C3-PFBS",          "PFBS",   "surrogate"),
    ("M3PFHxS",  "13C3-PFHxS",         "PFHxS",  "surrogate"),
    ("M8PFOS",   "13C8-PFOS",          "PFOS",   "surrogate"),
    ("M3HFPO",   "13C3-GenX (HFPO-DA)","GenX",   "surrogate"),
    ("M8FOSA",   "13C8-FOSA",          "FOSA",   "surrogate"),
    ("M2-4:2FTS","13C2,D4-4:2FTS",     "4:2FTS", "surrogate"),
    ("M2-6:2FTS","13C2,D4-6:2FTS",     "6:2FTS", "surrogate"),
    ("M2-8:2FTS","13C2,D4-8:2FTS",     "8:2FTS", "surrogate"),
    ("M2-10:2FTS","13C2,D4-10:2FTS",   "10:2FTS","surrogate"),
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
    ("TIS", "Aquatic Tissue",       "ng/g", ["EPA_1633A", "FDA_32PFAS"],False, 28),
    ("MEAT","Meat / Muscle",        "ng/g", ["FDA_32PFAS"],             False, 28),
    ("EGG", "Eggs",                 "ng/g", ["FDA_32PFAS"],             False, 28),
    ("FISH","Fish / Seafood",       "ng/g", ["FDA_32PFAS"],             False, 28),
    ("MILK","Milk",                 "ng/g", ["FDA_32PFAS"],             False, 14),
    ("FEED","Animal Feed",          "ng/g", ["FDA_32PFAS"],             False, 60),
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

# ── Calibration ladders per method (working ranges) ──────────────────────────
CAL_LADDERS = {
    "FDA_32PFAS": [20.0, 10.0, 5.0, 2.5, 1.25, 0.625, 0.313, 0.156, 0.078, 0.039],  # ng/mL
    "EPA_537_1":  [2.0, 4.0, 8.0, 16.0, 40.0, 80.0, 160.0],                          # ng/L (ppt)
    "EPA_1633A":  [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0],                      # ng/mL (verify)
}


def native_count() -> int:
    return len(NATIVE_ANALYTES)


def is_count() -> int:
    return len(INTERNAL_STANDARDS)
