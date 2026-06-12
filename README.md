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
| Native target analytes (AnalysisServices) | 34 | `analysis_services.csv` |
| Isotopically-labeled IS / surrogates | 21 | `internal_standards.csv` |
| Methods (FDA 32-PFAS, EPA 537.1, EPA 1633A) | 3 | `methods.csv` |
| Sample types (matrices) | 14 | `sample_types.csv` |
| Sample containers (PFAS-safe) | 7 | `containers.csv` |
| Storage locations (with target temps) | 7 | `storage_locations.csv` |
| Preservations | 5 | `preservations.csv` |
| Sample points (placeholder) | 5 | `sample_points.csv` |

Each native analyte is pre-linked to its surrogate/internal standard per the
FDA Table 9-1 mapping (e.g. PFOA→M8PFOA, PFTrDA→MPFDoA), and the 12 analytes
with no commercially matched labeled standard are flagged `NC` so the QC
engine applies the N.C. qualifier and the 40–140% recovery tier automatically.

> **Placeholders:** values marked `PLACEHOLDER` (e.g. PFTrDS CAS) and the
> EPA 1633A per-analyte limits must be confirmed against your standard COAs
> and your purchased copy of the method before production use.

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
content/EnvironmentalReading ◀──────── senaite_connector.push_sensor_reading
setuphandlers.py (install)             pipeline.py (per-batch processing)
```

When the worker pushes results it uses the **same analyte keywords** created
here, so results land on the correct AnalysisService without manual mapping.

---

## Custom content types added

- **Reagent** — a barcode-scanned reagent/standard lot (catalog #, lot #,
  expiry, class, scan count). Created on first scan by the extraction-log API.
- **EnvironmentalReading** — a temperature/humidity reading from a monitored
  location (supports Maine CMR Ch.263 continuous monitoring; carries a
  NIST-verified flag and out-of-range flag).

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
│   │   ├── reagent.py               Reagent content type
│   │   └── envreading.py            EnvironmentalReading content type
│   └── profiles/default/            GenericSetup XML (metadata, types, registry)
└── pfas_pipeline/                   the out-of-process worker (QC engine, etc.)
```
