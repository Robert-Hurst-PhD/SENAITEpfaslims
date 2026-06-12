"""
Extraction Log API — runs on the lab tablet (or any browser).

The technician opens http://<server>:9000 on the prep-room tablet:
  POST /log/start            → open a new extraction log for a batch
  POST /log/{batch}/scan     → barcode scan event (reagent traceability)
  POST /log/{batch}/step     → log an extraction step (weights, volumes)
  POST /log/{batch}/sign     → analyst/reviewer/supervisor sign-off
  GET  /log/{batch}          → current log state
  GET  /reagents/expiring    → inventory expiry dashboard

Each saved log lands in /data/extraction_logs/{batch}_extraction.json,
which the pipeline watcher automatically attaches to the matching
instrument run and embeds into the report PDF.
"""

from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pfas_pipeline.barcode import ReagentCatalog, ExtractionLog

LOG_DIR = Path(os.environ.get("EXTRACTION_LOG_DIR", "/data/extraction_logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PFAS Extraction Log")
catalog = ReagentCatalog(LOG_DIR / "reagent_catalog.json")
_active: dict[str, ExtractionLog] = {}


class StartReq(BaseModel):
    batch_id: str
    analyst: str
    matrix: str

class ScanReq(BaseModel):
    barcode: str
    step: str = ""
    description: str = ""
    manufacturer: str = ""
    reagent_class: str = "default"

class StepReq(BaseModel):
    step: str
    detail: str = ""
    value: str = ""

class SignReq(BaseModel):
    role: str       # analyst / reviewer / supervisor
    initials: str


def _get(batch_id: str) -> ExtractionLog:
    if batch_id not in _active:
        raise HTTPException(404, f"No active log for {batch_id}")
    return _active[batch_id]


@app.post("/log/start")
def start_log(req: StartReq):
    log = ExtractionLog(req.batch_id, req.analyst, req.matrix)
    _active[req.batch_id] = log
    return {"ok": True, "batch_id": req.batch_id}


@app.post("/log/{batch_id}/scan")
def scan(batch_id: str, req: ScanReq):
    log = _get(batch_id)
    result = log.scan_reagent(
        catalog, req.barcode, step=req.step,
        description=req.description, manufacturer=req.manufacturer,
        reagent_class=req.reagent_class,
    )
    log.save(LOG_DIR / f"{batch_id}_extraction.json")
    # result includes expiry_warning + label_job (ZPL) for new lots
    return result


@app.post("/log/{batch_id}/step")
def step(batch_id: str, req: StepReq):
    log = _get(batch_id)
    log.log_step(req.step, req.detail, req.value)
    log.save(LOG_DIR / f"{batch_id}_extraction.json")
    return {"ok": True, "steps": len(log.steps)}


@app.post("/log/{batch_id}/sign")
def sign(batch_id: str, req: SignReq):
    log = _get(batch_id)
    log.sign(req.role, req.initials)
    log.save(LOG_DIR / f"{batch_id}_extraction.json")
    return {"ok": True, "signoffs": log.signoffs}


@app.get("/log/{batch_id}")
def get_log(batch_id: str):
    path = LOG_DIR / f"{batch_id}_extraction.json"
    if batch_id in _active:
        return _active[batch_id].to_dict()
    if path.exists():
        import json
        return json.loads(path.read_text())
    raise HTTPException(404, "Not found")


@app.get("/reagents/expiring")
def expiring(days: int = 30):
    return catalog.expiring(days)
