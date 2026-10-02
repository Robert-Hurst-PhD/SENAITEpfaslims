# senaite.pfas — PFAS LIMS Extension for SENAITE

A SENAITE add-on that turns a stock SENAITE LIMS into a PFAS-aware laboratory
system: method profiles with per-method QC, a guided extraction that records
every lot used from the inventory, a run builder, an instrument import and QC
pipeline (an out-of-process worker), a data-review release gate, certificates
and state EDD export.

Where regulatory values come from is documented in
[docs/REFERENCES.md](docs/REFERENCES.md): the published methods
(EPA 537.1 v2.0, EPA 1633A; FDA C-010.04 through the lab as co-author),
ISO/IEC 17025:2017 and the state
EDD documents. Lab spreadsheets, instrument exports supplied for testing and
demo data are test material, never a source.

---

## Methods

| Method profile | Published method | Analytes configured | Notes |
|---|---|---|---|
| FDA 32-PFAS (food and feed) | FDA C-010.04 (in preparation; the lab is a co-author and the source for its values) | 32 | |
| EPA 537.1 (drinking water) | EPA 537.1 Version 2.0, EPA/600/R-20/006, March 2020 — 18 PFAS | 18 | |
| EPA 1633A (aqueous, solid, biosolids, tissue) | EPA Method 1633 Revision A, EPA 820-R-24-007, December 2024 — 40 PFAS | 40 | |

Each method owns its analyte set, Method × Matrix reportable panel, labelled
standards and links, QC criteria and rule switches, calibration levels,
correction factors and logbook sequence (see `CLAUDE.md` §3). A criterion that
is not configured is never replaced by a plausible default: the worker stops
with `UnconfiguredCriterion` naming what to set and where.

---

## What gets installed

Installing the `senaite.pfas` GenericSetup profile populates SENAITE setup from
the CSV files in `src/senaite/pfas/setupdata/`:

| Setup area | Count | Source file |
|---|---|---|
| Native target analytes (AnalysisServices) | 47 | `analysis_services.csv` |
| Isotopically labelled standards | 27 | `internal_standards.csv` |
| Methods | 3 | `methods.csv` |
| Sample types (matrices) | 14 | `sample_types.csv` |
| Sample containers | 7 | `containers.csv` |
| Storage locations | 7 | `storage_locations.csv` |
| Preservations | 5 | `preservations.csv` |
| Sample points (placeholders) | 5 | `sample_points.csv` |

The 47 analytes are the union across the three methods; each method reports a
subset, and the reportable panel is the Method × Matrix intersection, never the
flat list. Which labelled standard plays which role (extracted surrogate / EIS,
or injection internal standard) and what it is linked to is owned by each
method profile. Whether an analyte "has its own labelled standard" is derived
from those links per method, not stored. Values marked `PLACEHOLDER` or VERIFY
(some CAS / EDD codes, EPA 1633A placeholders) must be confirmed against the
sources in docs/REFERENCES.md.

---

## The bench chemist's day

- **Bench landing** — the extractions queue (not started / stage N of M /
  finished) and what needs attention: expired, quarantined, expiring and
  low-stock lots, and today's balance verification.
- **Guided extraction** — stage by stage: every reagent, prepared standard and
  consumable is picked from the inventory (usable lots only, the lab's last
  pick remembered, GS1 labels scanned, an unknown lot received in place);
  balances and pipettes are picked from the Facility QC units; per-sample
  amounts and final volumes and every dilution are recorded into the
  Extraction Log (FM-ENV-003). Anything that is missing or not usable needs a
  deviation note before the stage completes.
- **Inventory** — every use is recorded per lot, batch and stage; what is left
  is derived (received less uses); a recall search finds every batch that used
  a lot.
- **Logbooks** — form codes FM-ENV-001 Solvent/Reagent Prep, 002 Calibration
  Curve Prep, 003 Extraction Log, 004 Sample Processing, plus Chain of Custody,
  numbered from the logbook pool.

---

## Dependencies

Declared in `setup.py` and `profiles/default/metadata.xml`:

- **senaite.lims** ≥ 2.6.0 — the base LIMS (required)
- **senaite.core** ≥ 2.6.0 — content + workflow core (required)
- **senaite.app.listing** — listing views (required by core)
- **senaite.storage** — storage locations & sample storage hierarchy
- **senaite.queue** — async processing for large batches
- **senaite.patient** — *optional*, only for clinical matrices

The add-on's PDFs (extraction logbook, settings report) use WeasyPrint. The
worker container (`requirements.txt`): pandas, numpy, requests, reportlab (the
batch report), pypdf. Browser libraries are vendored under
`src/senaite/pfas/browser/static/vendor/` with their licences (MIT); the
camera scanner and OCR libraries (@zxing, tesseract.js) are Apache-2.0 and are
loaded from a CDN, never vendored, because Apache-2.0 is not compatible with
this project's GPLv2.

---

## Installation

### A. Development mount (matches docker-compose.yml)

The `senaite` service mounts the repository at `/addon`, so the add-on is
available without rebuilding the image:

```bash
docker compose up -d
# → http://localhost:8080
```

Then in the SENAITE UI:

1. **Site Setup → Add-ons** → install **senaite.pfas** (runs the GenericSetup
   profile and loads the setup data above; the profile re-runs on every start
   and migrates configured data without loss).
2. Confirm **Analysis Services** lists the 47 analytes and 27 labelled
   standards under the `PFAS - *` categories, and that Methods, Sample Types,
   Containers and Storage Locations are populated.

### B. Pip install into an existing SENAITE buildout

```bash
pip install -e src/   # or add senaite.pfas to your buildout eggs
# restart instance, then install via Add-ons control panel
```

---

## How the pieces connect

The add-on (in Plone, Python 2.7) and the `pfas_pipeline` worker (Python 3)
are one system: the worker talks to SENAITE only through JSON, and pure
add-on modules (calibration levels, QC schema, correction maths) are loaded by
the worker from the add-on so each rule lives once.

```
senaite.pfas (in SENAITE)                pfas_pipeline (worker container)
───────────────────────────             ─────────────────────────────────
method profiles (/data/qc)  ──────────▶ method_profiles.py (criteria per run)
guided extraction + Run Builder ─ sidecar ─▶ pipeline.py (run parameters,
  (FM-ENV-003 samples, dilutions)          extraction pedigree, dilutions)
Import Studio profiles  ──────────────▶ importer.py (refuses unknown formats)
Data Review release  ◀──── results ──── senaite_connector.py (neat result +
  (dilution appended as a retest)          dilution handed over)
```

`WIRING.md` (generated by `tools/wiring_map.py`) is the current map of what is
wired to what; `docs/history/` keeps dated audits and reviews.

---

## Content and storage

- **Reagent** and **PreparedStandard** content types hold the inventory (a
  prepared standard keeps its parent reagent lots). Lots are created in the
  Reagent Inventory or received in place during an extraction.
- **Facility monitoring** (ISO/IEC 17025 §6.4) lives in
  `/data/qc/facility_monitoring.db`, not in content types.
- **QC results** and the **inventory usage ledger** are SQLite databases under
  `/data/qc/`; logbooks, the extraction session and release checklists are
  ZODB annotations (see `CLAUDE.md` §7).

---

## File layout

```
senaite_pfas/
├── setup.py                  add-on package definition + dependencies
├── docker-compose.yml        zeo, senaite, pfas-worker, nginx
├── CLAUDE.md                 how this project is built (read first)
├── docs/REFERENCES.md        public sources for regulatory values; open checks
├── GAPS.md / DECISIONS.md / QUESTIONS.md   work log, decisions, open questions
├── WIRING.md                 generated wiring map
├── src/senaite/pfas/         the add-on (views, method profiles, inventory, ...)
│   └── setupdata/            setup CSVs loaded on install
├── pfas_pipeline/            the worker (import, QC engine, report, push)
├── tests/                    test suite (Python 3 and 2.7)
└── tools/                    audits and generators
```

---

## Licence

Copyright (C) 2026 PFAS Lab.

> **Set the copyright holder.** "PFAS Lab" is the author string already
> declared in `setup.py` and is used here for consistency, not because it
> is the legal holder. Replace it with the person or entity that actually
> holds copyright — it appears here and in `setup.py`.

This program is free software; you can redistribute it and/or modify it under
the terms of the **GNU General Public License version 2** as published by the
Free Software Foundation. See [LICENSE](LICENSE) for the full text.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

**Why GPLv2 and not something permissive.** This is a Plone add-on that imports
`senaite.core`, `senaite.lims` and `senaite.storage` directly, and all three are
GPLv2. It is therefore a derivative work, so a permissive licence is not
available to offer.
