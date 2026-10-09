# senaite.pfas — PFAS LIMS extension for SENAITE

A SENAITE 2.6 add-on that turns a stock SENAITE LIMS into a PFAS laboratory
system: method profiles with per-method QC, a guided extraction that records
every lot used from the inventory, a run builder, an instrument import and QC
pipeline (an out-of-process worker), a data-review release gate, certificates
and EDD export.

## Methods

| Method profile | Published method | Analytes |
|---|---|---|
| FDA 32-PFAS (food and feed) | FDA C-010 series | 32 |
| EPA 537.1 (drinking water) | EPA 537.1 Version 2.0, EPA/600/R-20/006 | 18 |
| EPA 1633A (aqueous, solid, biosolids, tissue) | EPA Method 1633 Revision A, EPA 820-R-24-007 | 40 |

Each method owns its analyte set, its method × matrix reportable panel,
labelled standards, QC criteria and rule switches, calibration levels,
correction factors and logbook sequence. A criterion that is not configured is
never replaced by a default: the worker reports what to set and where. Values
shipped as VERIFY or PLACEHOLDER must be confirmed by the laboratory against
the published method before production use.

## Requirements

- Docker with Docker Compose

The add-on depends on senaite.lims / senaite.core 2.6 and senaite.storage
(declared in `setup.py`). The worker image installs `requirements.txt`.

## Installation

```bash
git clone <this repository> senaite_pfas
cd senaite_pfas
docker compose up -d
```

The stack starts ZEO, SENAITE (port 8080, bound to this machine), nginx (port
80), the pipeline worker, the document renderer and the PDF text scanner. The
`senaite` service mounts this folder at `/addon` and installs the add-on in
development mode.

Then, signed in to SENAITE as the administrator:

1. **Site Setup → Add-ons** → install **senaite.pfas**. The profile loads
   the setup data in `src/senaite/pfas/setupdata/` (analysis services,
   labelled standards, methods, sample types, containers, storage locations,
   preservations) and the three method profiles.
2. **Configuration → Settings**: enter the laboratory's own values (staff,
   equipment, reporting limits, spike levels, regulatory limits, EDD profile
   codes). Nothing laboratory-specific is shipped.
3. Reach SENAITE through nginx (`http://<host>/senaite/`); put TLS in front
   of it (a reverse proxy or tunnel) for any access beyond the local network.

### Into an existing SENAITE buildout

```bash
pip install -e .        # or add senaite.pfas to the buildout eggs
```

Restart the instance and install the add-on from the Add-ons control panel.
The worker (`run_worker.py`, `pfas_pipeline/`) runs separately with Python 3
and reaches SENAITE over its JSON API.

## How the pieces connect

```
senaite.pfas (in SENAITE, Python 2.7)     pfas_pipeline (worker, Python 3)
─────────────────────────────────────     ─────────────────────────────────
method profiles (/data/qc)  ────────────▶ criteria per run
guided extraction + Run Builder ─ sidecar ▶ run parameters, extraction pedigree
Import Studio profiles  ────────────────▶ importer (refuses unknown formats)
Data Review release  ◀────── results ──── QC engine, SENAITE push
```

QC results, facility monitoring and the inventory ledger are SQLite databases
under `/data/qc/`; logbooks, extraction sessions and release checklists are
ZODB annotations; instrument reports and certificates are files under
`/data/`.

## Layout

```
setup.py              add-on package definition and dependencies
docker-compose.yml    zeo, senaite, pfas-worker, nginx, pfas-render, pfas-scan
Dockerfile.senaite    SENAITE image
Dockerfile.worker     worker image (requirements.txt)
nginx.conf            reverse proxy for SENAITE
run_worker.py         the worker's entry point
src/senaite/pfas/     the add-on
pfas_pipeline/        the worker (import, QC engine, report, push)
tools/pdfme/          document renderer service
tools/pdfscan/        PDF text scanner service
data/                 runtime folders (mounted volumes)
```

## Licence

This program is free software; you can redistribute it and/or modify it under
the terms of the **GNU General Public License version 2** as published by the
Free Software Foundation. See [LICENSE](LICENSE) for the full text.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

It imports `senaite.core`, `senaite.lims` and `senaite.storage`, which are
GPLv2, and is therefore distributed under the same licence.
