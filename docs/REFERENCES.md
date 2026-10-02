# References — where the system's values come from

Every method criterion, analyte list, limit, code and default that this system
ships must trace to a **publicly available source** listed here, or be marked
as the lab's own setting (entered in the UI and owned by the lab), or be
flagged **VERIFY** until it is. Identifiers below were checked against the
published documents on 2026-10-02.

## What is NOT a source

The following were used during development **only as test material**. They
never establish a regulatory value, an analyte list, a limit or a default, and
code, comments and documentation must not cite them as one:

- the lab's working spreadsheets (an FDA sample calculator workbook and an
  injection-list workbook) and anything "ported" from them;
- instrument exports supplied for testing (e.g. "Test Sample.csv" and the
  QC-coherent fixture derived from it) and the demo / seeded batches and
  samples in the development database;
- earlier tablet-service logs, catalogues or naming conventions.

Where older code or history still describes something as "from the
calculator" or "from the xlsm", that is a description of how it was first
typed in, not evidence. Such values are listed under *Open checks* until they
are confirmed against a source below.

## Published methods

| Method | Identifier | Date | Scope | Source |
|---|---|---|---|---|
| **FDA C-010.04** — PFAS in food and feed by LC-MS/MS (the revision this system implements) | FDA Foods Program Compendium, Method C-010.04 | in preparation; the lab is a co-author | the FDA method profile ("FDA 32-PFAS") | **the lab** — values are entered by the lab as a co-author of C-010.04; cite its section once published |
| FDA C-010.03 — Determination of 30 PFAS in Food and Feed using LC-MS/MS (predecessor, for background only) | Method C-010.03 | posted 2024-04-12 | 30 PFAS | <https://www.fda.gov/media/131510/download> — **not** the source for this system's FDA values |
| **EPA Method 537.1, Version 2.0** — Determination of Selected PFAS in Drinking Water by SPE and LC/MS/MS | EPA/600/R-20/006 | March 2020 | 18 PFAS in drinking water | <https://cfpub.epa.gov/si/si_public_record_report.cfm?Lab=NERL&dirEntryId=348508> |
| **EPA Method 1633, Revision A** — Analysis of PFAS in Aqueous, Solid, Biosolids, and Tissue Samples by LC-MS/MS | EPA 820-R-24-007 | December 2024 (supersedes all earlier 1633 versions) | 40 PFAS; non-potable water, soil, sediment, biosolids, landfill leachate, fish and shellfish tissue | <https://www.epa.gov/system/files/documents/2024-12/method-1633a-december-5-2024-508-compliant.pdf> · <https://www.epa.gov/cwa-methods/cwa-analytical-methods-and-polyfluorinated-alkyl-substances-pfas> |

Sections read and confirmed (2026-10-02) — cite these when a value is set
from them. FDA values come from C-010.04 through the lab (see above), so no
FDA sections are listed here until C-010.04 is published:

| Source | Section | States |
|---|---|---|
| EPA 537.1 v2.0 | §8.5 | samples extracted within 14 days; extracts analysed within 28 days of extraction |
| EPA 537.1 v2.0 | §9.3.3 | LFB: ≤ 2× MRL 50–150 %, above 70–130 % |
| EPA 537.1 v2.0 | §9.3.5.1 | surrogate recovery 70–130 % |
| EPA 537.1 v2.0 | §9.3.6.3 | LFSM 70–130 %; 50–150 % at or below 2× MRL |
| EPA 537.1 v2.0 | §9.3.7.2 / §9.3.7.4 | field duplicate RPD ≤ 30 %; LFSM duplicate RPD ≤ 30 % (≤ 50 % near the MRL) |

What each governs here:

- **Analyte sets** per method (Method Profile → master analyte set): the
  method's own target list.
- **QC acceptance criteria, frequencies and holding times** (Method Profile →
  QC tabs): the method's QC section; a value the lab tightens is the lab's
  setting and is entered as such (Project Specs or the method profile).
- **Calibration ranges**: EPA 1633A per-analyte ranges from its calibration
  table; the FDA ladder (0.039–20 ng/mL, doublings) as entered by the lab
  (C-010.04; DECISIONS 2026-10-02).
- **Labelled standards and their links** (surrogate / EIS / NIS): the method's
  isotope-dilution and internal-standard tables.

## Quality system

| Standard | Identifier | Governs |
|---|---|---|
| ISO/IEC 17025 — General requirements for the competence of testing and calibration laboratories | ISO/IEC 17025:2017 | traceability (§6.6 metrological traceability; §6.4 equipment), technical review before reporting (§7.8), records — see docs/ISO17025_DESIGN.md |

## Reporting and EDD

- **Maine DEP EGAD** electronic data deliverable: field layout and code lists
  (including the CAS_LUP parameter list used for EDD analyte codes) are the
  state's published EDD documents; the lab enters any client- or
  state-specific values in the EGAD settings. Codes not yet confirmed against
  the current list are marked VERIFY in the analyte reference.

## Open checks (VERIFY)

Values configured today but not yet confirmed against a source above. FDA
method values are the lab's (C-010.04, the lab co-authoring) and are not
listed here.

1. **EGAD codes** marked VERIFY in the analyte reference (e.g. PFTrDS, PFUnDS).
2. **Regulatory limits** shipped as seeds in regulatory_limits.py are
   UNVERIFIED until each is entered from its program's published source.
3. **EPA 1633A per-analyte QC limits** that are still placeholders in the
   method profile carry a VERIFY flag in the editor.
4. **src/senaite/pfas/analytes.py** (analyte names, IS MRM transitions,
   key-analyte flags) was first typed in from the lab's working spreadsheet.
   It seeds default method profiles and the key-analyte list and drives EDD
   internal-standard detection. EPA entries: confirm against the published
   tables; FDA entries are the lab's; MRM transitions are the lab's
   instrument method.

When a value is confirmed, record the source document, section or table, and
date in the method profile revision (Method Profiles → Issue) and remove it
from this list.
