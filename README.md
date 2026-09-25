# senaite.pfas — PFAS LIMS Extension for SENAITE

A SENAITE add-on that turns a stock SENAITE LIMS into a PFAS-aware laboratory
system. It ships the full analyte library, method-specific QC rulebooks,
barcode reagent tracking, an extraction-driven report pipeline, a run-queue
review workflow, and multi-vendor instrument import.

---

## What gets installed

Installing the `senaite.pfas` GenericSetup profile populates your SENAITE
setup automatically from the CSV files in `src/senaite/pfas/setupdata/`:

| Setup area | Count | Source file |
|---|---|---|
| Native target analytes (AnalysisServices) | 47 | `analysis_services.csv` |
| Isotopically-labeled IS / surrogates | 27 | `internal_standards.csv` |
| Methods (FDA 32-PFAS, EPA 537.1, EPA 1633A) | 3 | `methods.csv` |
| Sample types (matrices) | 14 | `sample_types.csv` |
| Sample containers (PFAS-safe) | 7 | `containers.csv` |
| Storage locations (with target temps) | 7 | `storage_locations.csv` |
| Preservations | 5 | `preservations.csv` |
| Sample points (placeholder) | 5 | `sample_points.csv` |

The 47 analytes are the UNION across all three methods; each method reports a
subset, and the reportable panel is the Method × Matrix intersection, never the
flat list (see `CLAUDE.md` §3):

| Method | Panel | Matrices |
|---|---|---|
| FDA 32-PFAS | 32 | 6 |
| EPA 537.1 | 18 | 3 |
| EPA 1633A | 40 | 9 |

The 27 labeled compounds are **26 surrogates + 1 injection internal standard**
(13C4-PFOA under FDA). Which compound plays which role is owned by the method
(`surrogate_is_chain`); the roles are treated differently under dilution — see
`docs/ISO17025_DESIGN.md` §5.

Each native analyte is pre-linked to its surrogate per the FDA Table 9-1
mapping (e.g. PFOA→M8PFOA, PFTrDA→MPFDoA), and the 19 analytes with no
commercially matched labeled standard are flagged `NC` so the QC engine applies
the N.C. qualifier and the 40–140% recovery tier automatically.

> **Placeholders are now enforced, not merely advised.** Values marked
> `PLACEHOLDER` (e.g. PFTrDS CAS) must still be confirmed against your standard
> COAs. But an acceptance criterion that is **not configured no longer falls
> back to a plausible default** — the run raises `UnconfiguredCriterion` and
> stops, naming the method, analyte, matrix, QC type and where to set it. This
> applies to recovery tiers, CCV windows and the EPA 1633A EIS limits.
>
> A limit the METHOD TEXT states (FDA §2024.10.1(5) surrogates 50–150%,
> EPA 537.1 §9.3.5 surrogates 70–130%) is *not* a placeholder: it is a cited
> regulatory value, it stands as the default, and it can be overridden from
> `qc_acceptance.SUR`. See `docs/ISO17025_DESIGN.md` §3b for why those two
> cases are treated differently.

---

## Dependencies (the add-ons required)

Declared in `setup.py` and `profiles/default/metadata.xml`:

- **senaite.lims** ≥ 2.6.0 — the base LIMS (required)
- **senaite.core** ≥ 2.6.0 — content + workflow core (required)
- **senaite.app.listing** — listing views (required by core)
- **senaite.storage** — storage locations & sample storage hierarchy
- **senaite.queue** — async processing so 18-sample / 600-page batches don't block the UI
- **senaite.patient** — *optional*, only if you add clinical matrices

Runtime libraries shared with the worker container: `pandas`, `reportlab`,
`pypdf`, `requests`, `pyyaml`.

---

## Installation

### A. Development mount (recommended, matches docker-compose.yml)

The `senaite` service mounts `./src` and sets `DEVELOP=/src/senaite.pfas`,
so the add-on is available without rebuilding the image:

```bash
docker compose up -d
# → http://localhost:8080  (admin/admin)
```

Then in the SENAITE UI:

1. **Site Setup → Add-ons** → install **senaite.pfas**
   (this runs the GenericSetup profile and loads all setup data above).
2. Confirm **Site Setup → Analyses Setup → Analysis Services** now lists the
   34 analytes + 21 internal standards under the `PFAS - *` categories.
3. Confirm **Methods**, **Sample Types**, **Containers**, **Storage Locations**
   are populated.

### B. Pip install into an existing SENAITE buildout

```bash
pip install -e src/   # or add senaite.pfas to your buildout eggs
# restart instance, then install via Add-ons control panel
```

---

## How the pieces connect to the pipeline

The add-on (in-Plone) and the `pfas_pipeline` worker (out-of-process) share
the same analyte definitions and method profiles:

```
senaite.pfas (in SENAITE)              pfas_pipeline (worker container)
─────────────────────────             ────────────────────────────────
analyte_reference.py  ───────────────▶ constants.py / method_profiles.py
setupdata/*.csv  → SENAITE objects     (same keywords used in results push)
content/Reagent     ◀───── register ── barcode.py (ReagentCatalog.scan)
setuphandlers.py (install)             pipeline.py (per-batch processing)
```

When the worker pushes results it uses the **same analyte keywords** created
here, so results land on the correct AnalysisService without manual mapping.

---

## Custom content types added

- **Reagent** — a barcode-scanned reagent/standard lot (catalog #, lot #,
  expiry, class, scan count). Created on first scan by the extraction-log API.
Facility/environmental monitoring (Maine CMR Ch.263 continuous monitoring, ISO
17025 §6.4) is **not** a content type. It lives in
`/data/qc/facility_monitoring.db` — `facility_qc.temperature_readings` plus
`temperature_studies` for the NIST verification metadata. An
`EnvironmentalReading` Dexterity type used to shadow that store and was removed
(`migrations/remove_envreading_type.py`); its only intended producer had no
caller, posted to a folder that did not exist, and used field names the schema
did not declare.

---

## File layout

```
senaite_pfas/
├── setup.py                         add-on package definition + dependencies
├── docker-compose.yml               4-service stack (zeo, senaite, worker, tablet UI)
├── src/senaite/pfas/
│   ├── configure.zcml               registers the GenericSetup profile
│   ├── content.zcml                 declares custom content types
│   ├── setuphandlers.py             loads setupdata CSVs into SENAITE on install
│   ├── analyte_reference.py         master analyte table (CAS, classes, IS links)
│   ├── setupdata/                   ← the populated placeholders (8 CSVs)
│   ├── content/
│   │   └── reagent.py               Reagent content type
│   └── profiles/default/            GenericSetup XML (metadata, types, registry)
└── pfas_pipeline/                   the out-of-process worker (QC engine, etc.)
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
available to offer. The repository briefly carried an MIT `LICENSE` that arrived
from GitHub's repository-creation dialog rather than from a decision; it has been
replaced. See `DECISIONS.md`, 2026-09-25.
