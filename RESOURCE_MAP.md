# SENAITE PFAS System — Complete Resource Map

This document maps every component in the modified SENAITE system, what it replaces from your two Excel workbooks, and how each module interacts with the others.

---

## 1. System topology

```
                          YOUR LAB NETWORK
 ┌──────────────────────────────────────────────────────────────────┐
 │                                                                  │
 │  Mass Spec PC                 Prep-room tablet      Raspberry Pi │
 │  (MassLynx export)            (browser)             (BME280/DHT22)│
 │       │ writes CSV                 │ HTTP                │ HTTP  │
 │       ▼                            ▼                     ▼       │
 │  S:\PFAS\Instrument_Output    :9000 extraction-ui   :8080 API    │
 │       │ (mounted read-only)        │                     │       │
 └───────┼────────────────────────────┼─────────────────────┼───────┘
         │                            │                     │
 ┌───────┼────────────────────────────┼─────────────────────┼───────┐
 │       ▼          DOCKER HOST       ▼                     ▼       │
 │  ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐  │
 │  │ pfas-worker  │   │ extraction-ui    │   │ senaite (Plone)  │  │
 │  │ watcher +    │──▶│ FastAPI          │──▶│ + senaite.pfas   │  │
 │  │ QC engine +  │   │ barcode scans    │   │ add-on           │  │
 │  │ report gen   │   │ extraction log   │   │                  │  │
 │  └──────┬───────┘   └──────────────────┘   └────────┬─────────┘  │
 │         │ REST (senaite.jsonapi)                    │ ZEO        │
 │         └──────────────────────────────────────────▶│            │
 │                                              ┌──────▼─────────┐  │
 │                                              │ zeo (ZODB)     │  │
 │                                              │ senaite-data   │  │
 │                                              └────────────────┘  │
 └──────────────────────────────────────────────────────────────────┘
```

---

## 2. Excel → Python module mapping

### From FDA_Sample_Calculator_V13.xlsm

| Excel sheet / VBA macro | Python module | Function |
|---|---|---|
| `DATA` table (75 columns) | `importer.py` | `load_instrument_csv()` → `InstrumentRow` objects |
| `Concat ID` formula | `importer.py` | `_build_concat_id()` — `name\|yyyymmddHHMMSS` |
| `ValidateInjectionNames` (VBA) | `importer.py` | `validate_injection_name()` — 7 regex patterns incl. StarLIMS 7-digit check |
| `IS Raw` sheet (`% from CAL` = response/avg) | `qc_engine.py` | `is_raw_check()` — flags `(SUR)` outside ±50% |
| `RT Deviation` sheet (`(rt/avg)-1`) | `qc_engine.py` | `rt_deviation_check()` — flags > ±0.10 min |
| `Qual-Quan Ratio` sheet | `qc_engine.py` | `qual_quan_check()` — flags `(QQ)` / `(N.C.)` for non-iso analytes |
| `Calibration %` sheet (R², col-26 %dev) | `qc_engine.py` | `calibration_check()` — flags `(CAL)` at R²<0.995 or dev>±20% |
| `LFSM & LFSMD` + userforms | `qc_engine.py` | `lfsm_check()` / `lfsmd_check()` — recovery 50–150%, RPD ≤30% |
| `CalculateMDL` (t(n-1,0.99)×σ, n≥7) | `qc_engine.py` | `calculate_mdl()` — MDLs + MDLb, blank rules |
| `Signal-to-Noise` sheet | `qc_engine.py` | `signal_to_noise_check()` — S/N ≥ 3 |
| `QC Log` sheet (Source/Analyte/Injection/Value/Issue) | `models.py` | `QCFlag` dataclass, consolidated in `RunQueue.auto_evaluate()` |
| `BuildSummary` + Summary Sheet qualifiers (`N.D.`, `< LOD`, `BLoQ`, `N.C.`, `SUR`) | `pipeline.py` | `build_summary()` — exact qualifier logic incl. blank≥sample → `< LOD` |
| `RunFullPDFPipeline` + `MergePDFsStable` (Adobe COM) | `report.py` | `generate_batch_report()` + `merge_external_pdfs()` (pypdf, no Acrobat) |
| Signature rows (`printWs` Analyst/Reviewer/Supervisor) | `report.py` | Signature block auto-filled from `ExtractionLog.signoffs` |

### From Sample_Injection_List.xlsm

| VBA macro | Python module | Function |
|---|---|---|
| `BuildPFASRun` | `injection_builder.py` | `build_standard_pfas_run()` — full recipe in one call |
| FDA CAL 1–10 ladder (20→0.039 ng/mL) | `injection_builder.py` | `FDA_CAL_LEVELS` constant |
| EPA 537 ladder (2→160 ppt) + QCS-1/2 | `injection_builder.py` | `EPA537_CAL_LEVELS` |
| `AddRotatingCCV` (bracket every N) | `injection_builder.py` | `_maybe_rotating_ccv()` — auto-inserts CCV every 10 injections |
| `AddBatchSamples` / `AddBatchLFBs` | `injection_builder.py` | `add_sample()` / `add_method_blank()` |
| LFSM userform (parent + spike selection) | `injection_builder.py` | `add_lfsm_pair()` — names match `parent; LFSM High Dup.` |
| `AddFinalSample` / `BuildFinalRun` | `injection_builder.py` | `finalize()` — closing CCV bracket |
| `CreateCSV` (autosampler export) | `injection_builder.py` | `to_csv()` |

---

## 3. New capabilities (not in Excel)

| Requirement (your words) | Module | How |
|---|---|---|
| "run Queue will prompt what QC should be looked for in the analysis of LFSMs, duplicates matrix blanks etc" | `run_queue.py` | `REVIEW_CHECKS` maps each QC type → required checks; `RunQueue.pending()` returns prompts like *"Verify LFSM recovery 50–150%"*; auto-resolved where the QC engine can decide, human-pending otherwise |
| "fetch processed samples and review them at home" | `pipeline.py` + `run_queue.py` | Watcher auto-runs the pipeline when the CSV lands; `RunQueue.save()/load()` persists review state as JSON; everything also lands in SENAITE accessible via browser/VPN |
| "PDF creation … dependent on the extraction during analysis … linked to the barcode scanning of reagents" | `barcode.py` + `report.py` | `ExtractionLog` records every scan + step; `generate_batch_report()` embeds the reagent table (Cat#/Lot#/Expiry) and extraction steps directly into the report — no more collecting loose PDFs from `S:\PFAS` |
| "first detected lot number is found and then an expiration date is created" | `barcode.py` | `ReagentCatalog.scan()` — new lots auto-registered with expiry (vendor GS1 date or class-based shelf life) |
| "If a new reagent/solvent is created then a barcode is issued to the label maker" | `barcode.py` | `make_label_zpl()` returns Zebra ZPL; send via `nc <printer> 9100` |
| "Automatically generate instrument injection sequences … accounts for QC rules" | `injection_builder.py` | CCV bracketing, LFSM adjacency, closing bracket all enforced structurally |
| "continuous monitoring of laboratory temperature and humidity … Raspberry Pi" | `senaite_connector.py` | `push_sensor_reading()` endpoint; RPi cron POSTs readings; NIST-traceable verification metadata per Maine CMR Ch.263 p.41 |
| "Each batch (18 Samples) is 600 pages" | `report.py` | Single generated PDF with bookmarks per section, exception-only tables (only flagged calibration/IS rows printed) — radically shorter, fully traceable |

---

## 4. Data flow — one batch, end to end

```
DAY 1 — EXTRACTION (prep room tablet)
  POST /log/start {batch_id, analyst, matrix}
  POST /log/{id}/scan  ──▶ ReagentCatalog: lot lookup / register / expiry warn
  POST /log/{id}/step  ──▶ weights, volumes, SPE lots
  POST /log/{id}/sign  ──▶ analyst sign-off
  └─▶ /data/extraction_logs/{batch}_extraction.json

DAY 1 — SEQUENCE (office)
  InjectionSequenceBuilder.build_standard_pfas_run(18 samples, LFSM parent, spike)
  └─▶ sequence.csv → MS autosampler
  └─▶ review_queue() → the QC checks each injection will need

DAY 1–2 — ACQUISITION (instrument runs overnight)
  MassLynx writes batch_260226.csv → S:\PFAS\Instrument_Output

DAY 2 — AUTO-PROCESSING (pfas-worker, no human)
  watcher detects stable CSV
  run_pipeline():
    importer → 75-col DATA rows
    validate injection names (StarLIMS DCU compatible)
    RunQueue.auto_evaluate() → all 6 QC sheets computed at once
    build_summary() → N.D./< LOD/BLoQ/N.C./SUR qualifiers
    generate_batch_report() → PDF w/ embedded extraction log + reagent lots
    SENAITE push: Batch + results + QC remarks + attachments

DAY 2 — REVIEW (from home)
  open SENAITE in browser, or load {batch}_queue.json
  queue.pending() → "Verify LFSM recovery 50–150%", "Verify blank…", …
  queue.accept(injection, check, "KP", comment)
  queue.is_complete → release batch in SENAITE
```

---

## 5. SENAITE object mapping

| Pipeline object | SENAITE portal_type | Notes |
|---|---|---|
| `Batch` | `Batch` | title = batch_id |
| Environmental sample | `AnalysisRequest` | `ClientSampleID` = StarLIMS 7-digit from injection name |
| Analyte result | `Analysis` | `Result` + `InterimFields` (RT, IS response, S/N) |
| `QCFlag` list | `Remarks` on Batch | consolidated QC Log text |
| Report PDF | `Attachment` on Batch | also senaite.impress-compatible |
| Extraction log JSON | `Attachment` on Batch | raw machine-readable copy |
| Reagent lot | `Reagent` (custom type) | falls back to remark if add-on type absent |
| RPi reading | `EnvironmentalReading` (custom type) | Maine CMR Ch.263 traceability |

The custom content types (`Reagent`, `EnvironmentalReading`, `QCFlag`) live in the `senaite.pfas` Plone add-on skeleton at `src/senaite.pfas/` — mounted into the container via `DEVELOP=/src/senaite.pfas` so edits hot-reload.

---

## 6. File inventory

```
senaite_pfas/
├── docker-compose.yml          4 services: zeo, senaite, pfas-worker, extraction-ui
├── Dockerfile.worker           python:3.12-slim worker image
├── requirements.txt
├── run_worker.py               watcher entry point
├── extraction_api.py           FastAPI tablet app (port 9000)
├── pfas_pipeline/
│   ├── constants.py            21 IS + 34 analytes + criteria + patterns + col map
│   ├── models.py               InstrumentRow, QCFlag, Batch, Reagent, …
│   ├── importer.py             CSV → typed rows; name validation; grouping
│   ├── qc_engine.py            all 6 QC checks + MDL  (the xlsm formulas)
│   ├── injection_builder.py    sequence builder (Sample_Injection_List port)
│   ├── run_queue.py            review prompts + persistence
│   ├── barcode.py              GS1/vendor parsing, lot registry, ZPL labels
│   ├── report.py               PDF generation + merge (replaces Adobe COM)
│   ├── senaite_connector.py    jsonapi REST client
│   └── pipeline.py             orchestrator + directory watcher
└── tests/
    └── test_pipeline.py        end-to-end smoke test (passing)
```

---

## 7. Start-up commands

```bash
# 1. Bring up the whole stack
docker compose up -d

# 2. First run only: install SENAITE
#    → http://localhost:8080  (admin/admin) → "Install SENAITE LIMS"

# 3. Tablet: open http://<host>:9000/docs for the extraction-log API

# 4. Drop an instrument CSV into the watched share to trigger the pipeline
#    (or run manually:)
docker compose exec pfas-worker python -c "
from pfas_pipeline.pipeline import run_pipeline
run_pipeline('/data/instrument_output/batch.csv', output_dir='/data/reports')"

# 5. Tail the worker
docker compose logs -f pfas-worker
```

---

## 8. Known gaps / next steps

1. **`senaite.pfas` Plone add-on skeleton** — the custom content types (`Reagent`, `EnvironmentalReading`) need ZCML/GenericSetup registration inside the Plone package; the connector degrades gracefully (remarks) until then.
2. **Spike-value source for LFSM** — the VBA userform let the analyst pick the spike conc.; currently passed as a parameter to `lfsm_check()`. Wire it into the run-queue prompt UI.
3. **MDL replicate selection UI** — `calculate_mdl()` is implemented; the workflow to designate which 7+ injections constitute the MDL study still needs a queue prompt.
4. **Column-index validation against your real export** — the importer maps by header name; verify one real MassLynx CSV against `_COL_MAP` (5-minute check).
5. **RPi sensor script** — a 20-line `curl` cron posting to `push_sensor_reading()`; happy to generate it.

---

## 9. Method Profile layer (added in re-evaluation passes)

The flat `CRITERIA` dict is superseded by `method_profiles.py`. Every QC limit now resolves through `get_profile(method).qc_rules(analyte, matrix, qc_type)`, so the same engine enforces three different rulebooks.

### Profiles shipped

| Profile | Source | Key distinctive rules |
|---|---|---|
| `FDA_32PFAS` | USDA/FDA 32-PFAS in Food v10 (5/5/26) + AOAC SMPR 2023.003 | r² ≥ **0.990**; three-tier recovery (80–120 big-four in egg/meat/seafood, 65–135 elsewhere, 40–140 no-labeled-std + RSDr≤30); CCV 70–130% **every 6**; surrogate 50–150% *guidance only*; ion ratio ±30%; **RRT ≤1% relative**; S/N≥3 at 0.039 (fallback 0.078); PFBA/PFPeA → LC-HRMS confirm %diff<20%; per-matrix sample factors (×0.5/×0.2/×2) |
| `EPA_537_1` | EPA/600/R-20/006 | IS **70–140% of last CCV AND ±50% of ICAL avg** (both must hold); surrogate 70–130%; low-level LFB/CCC 50–150%, mid/high 70–130%; CCV every 10; **calibration forced through origin** |
| `EPA_1633A` | EPA 1633A (Jan 2024) | EIS recovery **per-analyte × per-matrix** (Tables 6/8); wider ion-ratio window; every limit flagged `verify_against_method=True` |

### Per-analyte/matrix resolution examples (verified in regression)

```
FDA  PFOA   in deer muscle, LFSM →  80–120%   (tier 1)
FDA  PFOA   in water,       LFSM →  65–135%   (tier 2)
FDA  PFHpA  in deer muscle, LFSM →  65–135%   (tier 2)
FDA  PFTrDA in deer muscle, LFSM →  40–140%, RSDr≤30%  (tier 3, no labeled std)
```

### New profile-aware QC engine functions (`qc_engine.py`)

`recovery_check_profiled`, `rpd_check_profiled`, `ccv_check_profiled`, `calibration_check_profiled`, `is_check_profiled` (dual-condition for 537.1), `rrt_check_profiled` (relative vs absolute RT by method), `single_transition_confirm_needed` (PFBA/PFPeA HRMS prompt). Legacy flat-criteria functions retained for backward compatibility.

### Table 9-1 mapping (FDA)

`FDA_NATIVE_SURROGATE_MAP` encodes each native→surrogate pair (PFOA→M8PFOA, PFTrDA→MPFDoA, …, all Linear 1/x); surrogates quantified against `M4PFOA` (`FDA_SURROGATE_IS`) by mean response factor.

---

## 10. Vendor-agnostic import (`vendor_profiles.py`)

`load_instrument_csv(path, vendor=None)` now remaps vendor headers to canonical names before parsing. `vendor=None` auto-detects from the header row.

| Vendor key | Instrument software | Detection signal |
|---|---|---|
| `sciex` | SCIEX OS Analytics (FDA method platform) | `Component Name`, `Area Ratio` |
| `agilent` | MassHunter Quant | `Data File`, `ISTD Resp`, `Final Conc.` |
| `waters` | MassLynx / TargetLynx (QuanLynx) | `Sample Text`, `IS Area`, `Acq.Date` |
| `native` | Excel DATA table passthrough | `Injection Name` + `Compound Name` |

Add an instrument without code changes via `load_vendor_profile_yaml(path)` — a YAML file with `vendor`, `delimiter`, and a `map:` of their columns → canonical field names.

---

## 11. Method-driven injection templates (`injection_builder.py`)

The builder now pulls its sequence rules from the method profile:

- **FDA** (§2024.8.4): MeOH blank → CAL curve → MeOH blank → ICV → samples (CCV every 6) → LFSM/LFSMD → closing CCV
- **537.1 / 1633A**: CAL curve → ICV → opening CCV → MB → samples (CCV every 10) → LFSM/LFSMD → closing CCV

CCV interval is no longer hardcoded; `ccv_interval=None` (default) inherits the method's frequency.

---

## 12. Still outstanding (honest status)

1. **EPA 1633A per-analyte tables** — structure complete; representative limits in place but every value is `verify_against_method=True`. Populate `_1633A_EIS_OVERRIDES_AQUEOUS` (and add solid/biosolid/tissue tables) from your purchased method copy before production.
2. **SENAITE workflow event chain** (CoC received → run creation → extraction log → injection build) — designed in §4 but the Plone subscriber wiring is not yet written; this was deferred from the 5-pass scope.
3. **Waters LIMS port specifics** — sequence export is a swappable template; exact MassLynx sample-list import schema per version still needs the Waters support-portal spec.
4. **537.1 / 1633A injection ladders** for the builder — FDA + 537 ladders present; 1633A ladder not yet added.
