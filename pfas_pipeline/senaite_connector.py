"""
SENAITE Connector — pushes/pulls everything through senaite.jsonapi.

Endpoints used (SENAITE 2.x, senaite.jsonapi v1):
  GET  /@@API/senaite/v1/search?portal_type=...
  POST /@@API/senaite/v1/create
  POST /@@API/senaite/v1/update
  POST /@@API/senaite/v1/{portal_type}/{uid}

Mapping (your features → SENAITE objects):
  Batch                → Batch
  Injection (sample)   → AnalysisRequest  (ClientSampleID = StarLIMS 7-digit)
  Analyte result       → Analysis (Result + InterimFields for RT, IS, S/N)
  QC injections        → ReferenceSample / Duplicate / Blank worksheets
  QCFlag               → Remarks on the Analysis + custom log
  Reagent (barcode)    → custom content type 'Reagent' (or StockItem if
                         senaite.storage installed)
  ExtractionLog        → Attachment on the Batch (JSON + rendered PDF)
  Final report         → ARReport attachment (senaite.impress compatible)
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

import requests

from .models import Batch, QCFlag, SummaryResult
from .barcode import ExtractionLog

logger = logging.getLogger(__name__)


class SenaiteConnector:
    def __init__(
        self,
        base_url: str = "http://localhost:8080/senaite",
        username: str = "admin",
        password: str = "admin",
        timeout: int = 30,
    ):
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/@@API/senaite/v1"
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.timeout = timeout

    # ── low-level helpers ─────────────────────────────────────────────────────
    def _get(self, path: str, **params) -> dict:
        r = self.session.get(f"{self.api}/{path}", params=params,
                             timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict) -> dict:
        r = self.session.post(f"{self.api}/{path}", json=payload,
                              timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def search(self, **query) -> list[dict]:
        out = self._get("search", **query)
        return out.get("items", [])

    # ── Batch ────────────────────────────────────────────────────────────────
    def create_batch(self, batch: Batch, client_uid: str) -> str:
        """Create a SENAITE Batch; returns its UID."""
        existing = self.search(portal_type="Batch", title=batch.batch_id)
        if existing:
            batch.senaite_batch_uid = existing[0]["uid"]
            return existing[0]["uid"]

        res = self._post("create", {
            "portal_type": "Batch",
            "parent_path": "/senaite/batches",
            "title": batch.batch_id,
            "description": f"PFAS batch — {batch.matrix} — {batch.analyst}",
            "Client": client_uid,
        })
        uid = res["items"][0]["uid"]
        batch.senaite_batch_uid = uid
        return uid

    # ── Samples (AnalysisRequests) ───────────────────────────────────────────
    def find_sample_by_starlims(self, starlims_id: str) -> Optional[dict]:
        items = self.search(portal_type="AnalysisRequest",
                            getClientSampleID=starlims_id)
        return items[0] if items else None

    def push_result(
        self,
        sample_uid: str,
        analyte_keyword: str,
        result: SummaryResult,
        interims: dict | None = None,
    ):
        """
        Write one analyte result onto an AnalysisRequest.
        InterimFields carry RT, IS response, S/N for full traceability.
        """
        analyses = self.search(
            portal_type="Analysis",
            getAncestorsUIDs=sample_uid,
            getKeyword=analyte_keyword,
        )
        if not analyses:
            logger.warning("No Analysis %s on sample %s",
                           analyte_keyword, sample_uid)
            return

        uid = analyses[0]["uid"]
        payload = {
            "Result": (result.result_ppt
                       if result.result_ppt is not None
                       else result.qualifier),
            "Remarks": " ".join(result.flags) if result.flags else "",
        }
        if interims:
            payload["InterimFields"] = [
                {"keyword": k, "value": v} for k, v in interims.items()
            ]
        self._post(f"update/{uid}", payload)

    # ── QC flags → Remarks ───────────────────────────────────────────────────
    def push_qc_flags(self, batch_uid: str, flags: list[QCFlag]):
        """Attach the consolidated QC Log to the batch as a remark blob."""
        text = "\n".join(
            f"[{f.source}] {f.analyte} | {f.injection_name} | "
            f"{f.value} {f.issue}"
            for f in flags
        )
        self._post(f"update/{batch_uid}", {"Remarks": text})

    # ── Import Studio profile bridge ─────────────────────────────────────────
    def get_instrument_profile(self, vendor_key: str = "", version: str = "",
                               columns: "list | None" = None) -> dict:
        """
        Fetch a saved Import Studio column-mapping profile from SENAITE.

        Returns the profile dict ({"vendor": ..., "map": {...}, ...}) on success.
        Returns {"error": "..."} when no profile has been saved for this
        vendor_key+version — the importer should refuse and tell the user to open
        Import Studio.

        Raises requests.HTTPError / ConnectionError if SENAITE is unreachable.
        In strict mode (Round 8 Q-012), callers do NOT catch this exception —
        SENAITE downtime halts file processing.
        """
        payload: dict = {}
        if vendor_key:
            payload["vendor_key"] = vendor_key
        if version:
            payload["version"] = version
        if columns:
            # Let SENAITE identify the instrument from the file's own headers.
            # It owns the only vendor detector; the pipeline no longer keeps a
            # second one that could disagree with it.
            payload["columns"] = json.dumps(list(columns))
        r = self.session.post(
            f"{self.base}/@@pfas-instrument-profile",
            data=payload,
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    # ── Reagents (barcode registry) ──────────────────────────────────────────
    def register_reagent(self, reagent: dict) -> Optional[str]:
        """
        Register a reagent lot.  If senaite.storage is installed this can be a
        StorageSample; otherwise we use a SupplyOrder-style placeholder or a
        custom content type 'Reagent' if your add-on registers one.
        """
        try:
            res = self._post("create", {
                "portal_type": "Reagent",          # custom type in senaite.pfas
                "parent_path": "/senaite/reagents",
                "title": f"{reagent['catalog_number']} lot {reagent['lot_number']}",
                "description": reagent.get("description", ""),
                "CatalogNumber": reagent["catalog_number"],
                "LotNumber": reagent["lot_number"],
                "ExpiryDate": reagent["expiry_date"],
            })
            return res["items"][0]["uid"]
        except requests.HTTPError:
            logger.info("Custom Reagent type not installed — storing as remark")
            return None

    # ── Extraction log + report attachments ─────────────────────────────────
    def attach_file(self, parent_uid: str, file_path: str | Path,
                    label: str = "") -> Optional[str]:
        """Upload a file (extraction log JSON, report PDF) as an Attachment."""
        file_path = Path(file_path)
        import base64
        b64 = base64.b64encode(file_path.read_bytes()).decode()
        try:
            res = self._post("create", {
                "portal_type": "Attachment",
                "parent_uid": parent_uid,
                "AttachmentFile": {
                    "data": b64,
                    "filename": file_path.name,
                },
                "AttachmentKeys": label or file_path.stem,
            })
            return res["items"][0]["uid"]
        except requests.HTTPError as e:
            logger.error("Attachment upload failed: %s", e)
            return None

    # ── Environmental monitoring (Raspberry Pi POSTs here) ──────────────────
    def push_sensor_reading(self, location: str, temperature_c: float,
                            humidity_pct: float, sensor_id: str):
        """
        RPi端 cron POSTs readings; stored as a remark stream or custom type.
        Maine CMR Ch.263 p.41: each sensor verified against NIST reference.
        """
        try:
            self._post("create", {
                "portal_type": "EnvironmentalReading",   # custom type
                "parent_path": "/senaite/env-monitoring",
                "title": f"{location} {sensor_id}",
                "Temperature": temperature_c,
                "Humidity": humidity_pct,
            })
        except requests.HTTPError:
            logger.debug("EnvironmentalReading type not installed; skipping")
