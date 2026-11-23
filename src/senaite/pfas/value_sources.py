# -*- coding: utf-8 -*-
"""Where the system's values come from, and the one place that says so.

A method profile stores values, never the citation of a value: the public
source of every shipped value is listed here, and the Help entry "Where the
values come from" draws this list for an auditor. docs/REFERENCES.md is the
developers' copy of the same sources; tests/test_value_sources.py holds the
two to the same entries, so neither can drift.

  SOURCES                   [{"kind", "ref", "term", "states"}]
      kind "document": a published document, `ref` its identifier as
                       REFERENCES.md writes it;
      kind "section":  a section of a document, `ref` (source, section);
      kind "note":     a source described in prose, `ref` words of its title.
  help_rows()               [(term, what it states)] for the Help list
  citation_paths(profile)   [(path, value)] of the citation keys a stored
                            profile still holds
  strip_citations(profile)  drops them, returns the same list

A regulatory limit is not a method value: it keeps its source, which a
certificate prints beside it (regulatory_limits).

Test material (the lab's working spreadsheets, instrument exports supplied
for testing, demonstration data) is never a source and is never listed.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

_537 = "EPA 537.1 v2.0"
_MDL = "40 CFR 136 App. B Rev. 2 (EPA 821-R-16-006, Dec 2016)"
_533 = "EPA 533 (EPA 815-B-19-020)"
_1633 = "EPA 1633A (EPA 820-R-24-007)"
_8000D = "SW-846 Method 8000D, Rev. 5 (March 2018)"


def _doc(ref, term, states):
    return {"kind": "document", "ref": ref, "term": term, "states": states}


def _sec(source, section, states):
    return {"kind": "section", "ref": (source, section),
            "term": "{0}, {1}".format(source, section), "states": states}


def _note(ref, term, states):
    return {"kind": "note", "ref": ref, "term": term, "states": states}


SOURCES = [
    # ── the published methods ──────────────────────────────────────────────
    _doc("FDA Foods Program Compendium, Method C-010.04",
         "FDA Foods Program Compendium, C-010.04, PFAS in food and feed by LC-MS/MS",
         "The revision this system implements. It is in preparation and the laboratory is a "
         "co-author: the laboratory enters the FDA method's values itself, and its sections "
         "will be cited once it is published."),
    _doc("Method C-010.03",
         "FDA C-010.03, 30 PFAS in food and feed by LC-MS/MS",
         "The earlier revision, posted April 2024. Background only: it is not the source of "
         "this system's FDA values."),
    _doc("EPA/600/R-20/006",
         "EPA Method 537.1, Version 2.0, PFAS in drinking water by SPE and LC/MS/MS, EPA/600/R-20/006",
         "March 2020. 18 PFAS in drinking water."),
    _doc("EPA 820-R-24-007",
         "EPA Method 1633, Revision A, PFAS in aqueous, solid, biosolids and tissue samples by "
         "LC-MS/MS, EPA 820-R-24-007",
         "December 2024, superseding every earlier 1633 version. 40 PFAS in non-potable water, "
         "soil, sediment, biosolids, landfill leachate, and fish and shellfish tissue."),
    _doc("EPA 815-B-19-020",
         "EPA Method 533, PFAS in drinking water by isotope dilution anion exchange SPE and "
         "LC/MS/MS, EPA 815-B-19-020",
         "November 2019. 25 PFAS in drinking water. Its values are entered on the method's "
         "pages, each from its section or table."),

    # ── sections read and confirmed ────────────────────────────────────────
    _sec(_537, "§8.5", "Samples are extracted within 14 days, and extracts analysed within 28 days "
                       "of extraction."),
    _sec(_537, "§9.3.1", "Laboratory reagent blank: background below one third of the MRL; at or "
                         "above it, the analyte's results for the extraction batch are invalid."),
    _sec(_537, "§9.3.8", "Field reagent blank: invalid when an analyte is above one third of the "
                         "MRL."),
    _sec(_537, "§9.3.3", "Laboratory fortified blank: 50 to 150 % recovery at or below twice the "
                         "MRL, 70 to 130 % above it."),
    _sec(_537, "§7.2.1, §7.2.2, Table 3",
         "The internal standards 13C2-PFOA, 13C4-PFOS and d3-NMeFOSAA; the surrogates "
         "13C2-PFHxA, 13C3-HFPO-DA, 13C2-PFDA and d5-NEtFOSAA; and the internal standard each "
         "analyte is quantified against."),
    _sec(_537, "§9.3.4", "Internal standard areas within 50 % of the initial calibration's average "
                         "either way, and 70 to 140 % of the most recent continuing calibration "
                         "check."),
    _sec(_537, "§9.3.5.1", "Surrogate recovery 70 to 130 %."),
    _sec(_537, "§9.3.5.3", "A surrogate that still fails after re-extraction makes every result for "
                           "the sample suspect."),
    _sec(_537, "§9.3.6.3", "Laboratory fortified sample matrix: 70 to 130 %, and 50 to 150 % at or "
                           "below twice the MRL."),
    _sec(_537, "§9.3.7.2 / §9.3.7.4",
         "Field duplicate RPD at most 30 %; fortified sample matrix duplicate RPD at most 30 %, "
         "or 50 % near the MRL."),
    _sec(_537, "§9.3.5.1", "The continuing calibration check carries the surrogates, so surrogate "
                           "recovery is judged in it too."),
    _sec(_537, "§9.3.7.3", "The RPD of a fortified sample matrix and its duplicate is computed from "
                           "the two measured concentrations."),
    _sec(_537, "§9.3.10", "The quality control sample, which serves as the initial calibration "
                          "verification, is judged like a continuing calibration check."),
    _sec(_537, "§10.3", "Samples before the first continuing calibration check are not bracketed. "
                        "Blanks, fortified blanks, fortified sample matrices, duplicates and field "
                        "blanks do not count toward the check interval."),
    _sec(_537, "§11.7.2", "The method sets no retention-time window: the laboratory sets its own "
                          "from three standard deviations of its retention times."),
    _sec(_537, "§9.2.3, §9.2.4",
         "Initial precision and accuracy: four to seven fortified blanks near mid-calibration. "
         "Precision is their RSD, judged against the RSD maximum the laboratory enters for the "
         "fortified blank, a limit not yet confirmed against the method text; the mean recovery "
         "is within 30 % either way. Routine fortified blanks and control samples are never judged "
         "by RSD."),
    _sec(_537, "§9.2.6", "MRL confirmation: seven fortified blanks at the proposed MRL. The half "
                         "range of the prediction interval is 3.963 standard deviations; its upper "
                         "limit is at most 150 % and its lower at least 50 %."),
    _sec(_537, "§9.2.8.1, §9.2.8.2",
         "Detection limit: the standard deviation of at least seven fortified blanks over at "
         "least three days, times Student's t at 99 %, with no blank subtracted. MRL from blanks: "
         "the greater of the mean blank plus three standard deviations and three times the mean "
         "blank."),
    _sec(_537, "§9.2.2, §9.2.5, §9.2.7",
         "Low system background, a blank below one third of the MRL for each new lot and "
         "extraction port; peak asymmetry 0.8 to 1.5; quality control sample 70 to 130 %."),
    _sec(_MDL, "§2(b)-(e), §3, §4, Table 1",
         "The method detection limit. MDLs comes from at least seven spiked samples in at least "
         "three batches on three dates and MDLb from the method blanks; the MDL is the greater. "
         "It is verified at least every 13 months over 24 months of results. Student's t is "
         "the addendum's Table 1 value where the table lists the number of replicates, else the "
         "single-tailed 99th percentile."),
    _sec(_MDL, "§4(f) (Ongoing Annual Verification)",
         "The existing MDL may be kept when the verified MDL is within 0.5 to 2.0 times it and "
         "fewer than 3 % of the method blanks are above it. The procedure sets no rounding: an "
         "approved MDL is rounded as the certificate prints it."),
    _sec(_MDL, "Scope and Application, §2(d)(ii)-(iii), Addendum (3), §4(b)",
         "No blank subtraction: spiked samples are made from a clean reference matrix and taken "
         "as measured; the background enters through the method blanks; only results at the same "
         "spiking level are pooled."),

    # ── what each governs ───────────────────────────────────────────────────
    _note("Analyte sets", "Analyte sets",
          "Each method's analytes are its own published target list."),
    _note("QC acceptance criteria, frequencies and holding times",
          "QC acceptance criteria, frequencies and holding times",
          "From the method's quality control section. A value the laboratory tightens is the "
          "laboratory's own setting, entered on the method or on a project."),
    _note("Calibration ranges", "Calibration ranges",
          "EPA 1633A: each analyte's range from the method's Table 4, from its CS1 to its highest "
          "listed standard, each point double the last. FDA: 0.039 to 20 ng/mL, each point double "
          "the last, as the laboratory entered it."),
    _note("standards and their links", "Isotope standards and their links",
          "EPA 1633A: the extracted internal standards of Table 6, each an isotopologue of its "
          "own, Table 6's 13C8-PFOSA being 13C8-FOSA here; the non-extracted internal standards "
          "of Table 1, and the one each extracted standard is quantified against, from Table 10; "
          "the non-extracted standard area window of §14.9, 50 to 200 % of the initial "
          "calibration's mean area. A supplier's M-number counts carbon-13 atoms only."),

    # ── reporting and the EDD ───────────────────────────────────────────────
    _note("DEP", "The state's electronic data deliverable, version 6",
          "The state's published EDD documents: the field layout and code lists, including the "
          "CAS parameter list for analyte codes; the weight-basis codes WET, DRY, LIP and NA from "
          "the version 6 data element dictionary, Appendix 1. Which basis a matrix is reported "
          "on is the laboratory's setting."),
    _note("EPA 1633A calibration verification", "EPA 1633A, §14.3.3, §9.7, §9.9",
          "Calibration verification recovery 70 to 130 %. There is no separate initial "
          "verification criterion, so it is judged with the continuing window. Matrix spikes and "
          "duplicates carry no method criterion: matrix spikes are generally not required (§9.9) "
          "and a duplicate's RPD criterion is the requestor's (§9.7); their windows are the "
          "laboratory's own."),

    # ── manual integration ──────────────────────────────────────────────────
    _note("Manual Integration Technical Assistance Document",
          "VELAP Manual Integration Technical Assistance Document, 2016",
          "Procedures for Ensuring Defensibility of Manual Integrations: the reasons for a manual "
          "integration (2.1 to 2.2), improper practices (3.3 to 3.4) and the documentation "
          "minimum (5.2)."),
    _note("Manual Integration Policy and Technical Assistance Document",
          "Manual Integration Policy and Technical Assistance Document, 2010",
          "Further reasons, such as a co-eluting interferent, matrix interference and peaks that "
          "fail to separate, and further improper practices."),

    # ── the co-eluting pair fit ─────────────────────────────────────────────
    _note("A Pragmatic Introduction to Signal Processing",
          "T. C. O'Haver, A Pragmatic Introduction to Signal Processing",
          "Fitting overlapping peaks together by iterative least squares."),
    _note("Characterization of Exponentially Modified Gaussian Peaks",
          "E. Grushka, Analytical Chemistry 44 (1972) 1733-1738",
          "The exponentially modified Gaussian as the shape of a chromatographic peak."),
    _note("Reconstruction of chromatographic peaks",
          "Y. Kalambet and others, Journal of Chemometrics 25 (2011) 352-356",
          "Deconvolving chromatographic peaks as exponentially modified Gaussians."),
    _note("A Subspace, Interior, and Conjugate",
          "M. A. Branch, T. F. Coleman, Y. Li, SIAM Journal on Scientific Computing 21 (1999) 1-23",
          "The trust-region reflective method by which a co-eluting pair's ten parameters are "
          "fitted within their bounds."),

    # ── the quality system ──────────────────────────────────────────────────
    _doc("ISO/IEC 17025:2017",
         "ISO/IEC 17025:2017, competence of testing and calibration laboratories",
         "Metrological traceability (§6.6), equipment (§6.4), the technical review before "
         "reporting (§7.8) and records."),
    _doc("Kell 1975",
         "G. S. Kell, J. Chem. Eng. Data 20 (1975) 97-105",
         "The density of air-free water by temperature, used for gravimetric pipette "
         "calibration."),
    _doc("ISO 8655-2",
         "ISO 8655-2, piston-operated volumetric apparatus: pipettes",
         "The terms of the pipette check, systematic and random error, and their maximum "
         "permissible values, which the laboratory enters per pipette. No value is shipped."),
    _doc("ISO 8655-6",
         "ISO 8655-6, piston-operated volumetric apparatus: gravimetric methods",
         "The factor that turns a weighed mass into a volume, with air at 0.0012 g/mL and weights "
         "at 8.0 g/mL; checked against its table, 1.0029 µL/mg at 20 °C and 1.0040 at 25 °C."),

    # ── the calibration range, curve fit and origin ────────────────────────
    _sec(_537, "§3.15, §9.3.1, pp. 6, 21",
         "The MRL is no lower than the lowest calibration standard, and an estimate below the "
         "lowest standard is allowed for blank contamination only, not for sample results. A "
         "sample reads a quadratic curve only between its lowest and highest calibrator; a "
         "blank keeps its reading."),
    _sec(_537, "§10.2.6, §10.2.7, pp. 27-28",
         "A linear or quadratic curve, always forced through zero, weighted if necessary; each "
         "calibration level calculated against its regression equation. Force fits no constant "
         "term, and a calibrator with no reading on the curve fails its point."),
    _sec(_537, "§11.7.6, p. 32",
         "No extrapolation beyond the calibration range: a result above it is reported from a "
         "dilution, else printed above the top of the range with E."),
    _sec(_533, "§10.3.2, §10.3.5, pp. 24-25",
         "A linear or quadratic curve, weighting allowed, forced through the origin; each level "
         "calculated against its regression equation."),
    _sec(_533, "§12.2, §12.5, pp. 30-31",
         "Only values between the MRL and the highest calibration standard are reported; no "
         "extrapolation beyond the calibration range."),
    _sec(_1633, "§10.3.3.2 Note, p. 28",
         "A weighted or non-linear regression is weighted inversely to concentration and not "
         "forced through zero. The help entry on the calibration curve names it; no method's "
         "text is checked against its settings."),
    _sec(_1633, "§13.4 and Note, §15.4.2.3, pp. 40, 46",
         "A response above the calibration range is diluted; an undiluted result above it only "
         "after consulting the client, clearly identified and qualified. Release waits for the "
         "reviewer's reason, and the certificate prints it above the top of the range with E."),
    _sec(_1633, "§15.4.2.1, Glossary, pp. 46, 66",
         "A result below the LOQ is reported as below the LOQ, which is at or above the lowest "
         "calibration standard."),
    _sec(_8000D, "§11.0, §11.5, pp. 26, 32",
         "No extrapolation above or below the standards, whatever the model; the model must be "
         "continuous and monotonic across the calibration range, so a quadratic that turns "
         "within its range is refused; samples above the range are diluted; zero is not a "
         "calibration point."),
    _sec(_8000D, "§11.5.1 Note, §11.5.2, §11.5.2.1, §11.5.3, pp. 33-37",
         "An average response factor is a line forced through the origin, so its origin is Force "
         "and it is not weighted; weights are 1, 1/x or 1/x squared; forcing through the origin "
         "is not including the origin as a point; a weighted line is not forced; a non-linear "
         "curve may be weighted or forced."),
    _sec(_8000D, "§11.5.6.6, p. 41",
         "No point is removed from within the calibration range while its ends are kept; the "
         "range may be narrowed at its ends."),
    _sec("EPA CLP SOW SFAM02.1 (February 2026)", "Exhibit G, Table 1, p. G-28",
         "The laboratory's flags: J below the adjusted quantitation limit, E for a concentration "
         "above the upper limit of the calibration range, D for a secondary dilution. E is the "
         "certificate's reporting rule for a result above the range."),
    _sec("EPA NFG Organic Superfund Data Review (EPA 540-R-20-005, November 2020)",
         "Table 1, Part A §VI E.3, pp. 6, 10",
         "A data validator's qualifiers have no E, and a result above the range not properly "
         "diluted is qualified J: the electronic data deliverable issues E through the state's "
         "qualifier map."),

    # ── a citation once stored in a profile, kept as it was stored ─────────
    _sec("FDA (as stored in the profile)", "§2024.10.1(5)",
         "Surrogate recovery is guidance only. Copied as the FDA method profile stored it; the "
         "FDA method's values are the laboratory's, as a co-author of C-010.04."),
]


def help_rows():
    """[(term, what it states)], in SOURCES' order: the Help entry's list."""
    return [(s["term"], s["states"]) for s in SOURCES]


# ── the citation keys a stored profile may still hold ────────────────────────
# Each is a value's published source stored beside it. Named by path, never
# by key alone: "source" elsewhere in a profile names a lot.

def citation_paths(profile):
    """[(path tuple, stored value)] of every citation key `profile` holds:
    a QC tier's `citation`, the method-text surrogate window's `citation`,
    an isotope standard's `source`, the calibration levels' `levels_source`."""
    out = []
    profile = profile if isinstance(profile, dict) else {}
    qca = profile.get("qc_acceptance")
    for qc in sorted(qca) if isinstance(qca, dict) else []:
        entry = qca[qc]
        tiers = entry.get("tiers") if isinstance(entry, dict) else None
        for i, tier in enumerate(tiers if isinstance(tiers, list) else []):
            if isinstance(tier, dict) and "citation" in tier:
                out.append((("qc_acceptance", qc, "tiers", i, "citation"), tier["citation"]))
    eng = profile.get("engine")
    fb = eng.get("surrogate_fallback") if isinstance(eng, dict) else None
    if isinstance(fb, dict) and "citation" in fb:
        out.append((("engine", "surrogate_fallback", "citation"), fb["citation"]))
    ls = profile.get("labelled_standards")
    for kw in sorted(ls) if isinstance(ls, dict) else []:
        if isinstance(ls[kw], dict) and "source" in ls[kw]:
            out.append((("labelled_standards", kw, "source"), ls[kw]["source"]))
    iv = profile.get("instrument_verification")
    cal = iv.get("calibration") if isinstance(iv, dict) else None
    if isinstance(cal, dict) and "levels_source" in cal:
        out.append((("instrument_verification", "calibration", "levels_source"), cal["levels_source"]))
    return out


def strip_citations(profile):
    """Drop every citation key from `profile` (in place); returns what
    citation_paths listed before."""
    found = citation_paths(profile)
    for path, _value in found:
        node = profile
        for step in path[:-1]:
            node = node[step]
        node.pop(path[-1], None)
    return found
