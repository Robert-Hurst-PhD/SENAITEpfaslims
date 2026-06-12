"""
Barcode & Reagent Traceability System.

Workflow (matches your requirement):
  1. Technician scans a reagent barcode during extraction.
  2. lookup() parses Cat# + Lot# (GS1-128 or vendor-specific formats).
  3. If the lot is NEW → register it, auto-assign expiry, optionally emit a
     label-printer job (ZPL) for an internal barcode.
  4. Every scan is appended to the active ExtractionLog, which is later
     attached to the batch and embedded in the final report PDF.

Storage backend is a simple JSON catalogue here; in production this is the
SENAITE custom content type (see senaite_connector.register_reagent).
"""

from __future__ import annotations
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import Reagent


# Default shelf-life by reagent class when vendor expiry is unknown
DEFAULT_SHELF_LIFE_DAYS = {
    "solvent":   365,
    "standard":  180,    # PFAS native/labeled standards
    "spe":       730,    # SPE cartridges
    "salt":      1825,
    "default":   365,
}

# ── Barcode parsers ───────────────────────────────────────────────────────────
# GS1-128 Application Identifiers: (01) GTIN, (10) Lot, (17) Expiry YYMMDD
_GS1_RE = re.compile(
    r'\(?01\)?(?P<gtin>\d{14})'
    r'(?:\(?17\)?(?P<exp>\d{6}))?'
    r'(?:\(?10\)?(?P<lot>[A-Za-z0-9\-./]+))?'
)
# Vendor style: CAT#|LOT# or CAT# LOT#
_SIMPLE_RE = re.compile(
    r'^(?P<cat>[A-Z0-9][A-Z0-9\-\.]{2,})[|; ]+(?P<lot>[A-Z0-9][A-Z0-9\-\.]{2,})$',
    re.IGNORECASE,
)


def parse_barcode(raw: str) -> dict:
    """
    Parse a scanned barcode string into {catalog_number, lot_number, expiry}.
    Supports GS1-128 and simple CAT|LOT vendor formats.
    """
    raw = raw.strip()
    m = _GS1_RE.search(raw)
    if m and m.group("gtin"):
        exp = None
        if m.group("exp"):
            try:
                exp = datetime.strptime(m.group("exp"), "%y%m%d")
            except ValueError:
                pass
        return {
            "catalog_number": m.group("gtin"),
            "lot_number": m.group("lot") or "",
            "expiry": exp,
            "format": "GS1-128",
        }
    m = _SIMPLE_RE.match(raw)
    if m:
        return {
            "catalog_number": m.group("cat"),
            "lot_number": m.group("lot"),
            "expiry": None,
            "format": "vendor",
        }
    # Fallback: whole string is the catalog number
    return {"catalog_number": raw, "lot_number": "", "expiry": None,
            "format": "raw"}


# ── Catalogue ─────────────────────────────────────────────────────────────────
class ReagentCatalog:
    """
    First-detected-lot registry: 'the first detected lot number is found and
    then an expiration date is created.'
    """

    def __init__(self, store_path: str | Path = "reagent_catalog.json"):
        self.store_path = Path(store_path)
        self._items: dict[str, dict] = {}
        if self.store_path.exists():
            self._items = json.loads(self.store_path.read_text())

    def _key(self, cat: str, lot: str) -> str:
        return f"{cat}::{lot}"

    def scan(
        self,
        raw_barcode: str,
        description: str = "",
        manufacturer: str = "",
        reagent_class: str = "default",
        scanned_by: str = "",
    ) -> dict:
        """
        Main entry point for a barcode scan event.
        Returns {reagent, is_new, expiry_warning, label_job}.
        """
        parsed = parse_barcode(raw_barcode)
        cat, lot = parsed["catalog_number"], parsed["lot_number"]
        key = self._key(cat, lot)
        now = datetime.now()

        is_new = key not in self._items
        if is_new:
            expiry = parsed["expiry"]
            if expiry is None:
                days = DEFAULT_SHELF_LIFE_DAYS.get(
                    reagent_class, DEFAULT_SHELF_LIFE_DAYS["default"])
                expiry = now + timedelta(days=days)
            reagent = Reagent(
                barcode=raw_barcode,
                catalog_number=cat,
                lot_number=lot,
                description=description,
                manufacturer=manufacturer,
                expiry_date=expiry,
                first_seen=now,
            )
            self._items[key] = {
                **asdict(reagent),
                "expiry_date": expiry.isoformat(),
                "first_seen": now.isoformat(),
                "scan_count": 1,
                "scans": [{"at": now.isoformat(), "by": scanned_by}],
            }
        else:
            entry = self._items[key]
            entry["scan_count"] += 1
            entry["scans"].append({"at": now.isoformat(), "by": scanned_by})
            expiry = datetime.fromisoformat(entry["expiry_date"])

        self._save()

        expired = expiry < now
        expiring_soon = expiry < now + timedelta(days=30)

        return {
            "catalog_number": cat,
            "lot_number": lot,
            "is_new_lot": is_new,
            "expiry_date": expiry.isoformat(),
            "expired": expired,
            "expiry_warning": (
                "EXPIRED — do not use" if expired
                else "Expires within 30 days" if expiring_soon
                else None
            ),
            # If a brand-new in-house reagent has no vendor barcode,
            # emit a label job for the label printer
            "label_job": self.make_label_zpl(cat, lot, expiry) if is_new else None,
        }

    def _save(self):
        self.store_path.write_text(json.dumps(self._items, indent=2, default=str))

    # ── Label printer (ZPL for Zebra printers) ────────────────────────────────
    @staticmethod
    def make_label_zpl(cat: str, lot: str, expiry: datetime) -> str:
        """
        'If a new reagent/solvent is created then a barcode is issued to the
        label maker.'  Returns ZPL II for a 2"x1" label with Code-128 barcode.
        Send to printer:  cat label.zpl | nc <printer-ip> 9100
        """
        payload = f"{cat}|{lot}"
        return (
            "^XA"
            "^FO20,20^A0N,28,28^FD" + cat + "^FS"
            "^FO20,55^A0N,24,24^FDLot: " + lot + "^FS"
            "^FO20,85^A0N,24,24^FDExp: " + expiry.strftime("%Y-%m-%d") + "^FS"
            "^FO20,120^BY2^BCN,60,Y,N,N^FD" + payload + "^FS"
            "^XZ"
        )

    # ── Inventory queries ─────────────────────────────────────────────────────
    def expiring(self, within_days: int = 30) -> list[dict]:
        cutoff = datetime.now() + timedelta(days=within_days)
        return [
            v for v in self._items.values()
            if datetime.fromisoformat(v["expiry_date"]) <= cutoff
        ]

    def lots_for(self, catalog_number: str) -> list[dict]:
        return [v for v in self._items.values()
                if v["catalog_number"] == catalog_number]


# ── Extraction Log ────────────────────────────────────────────────────────────
class ExtractionLog:
    """
    Digital extraction log — replaces the paper sheet.
    Every barcode scan during extraction is recorded here; the log is attached
    to the batch and rendered into the final report PDF (your requirement:
    'PDF creation will need to be dependent on the extraction during analysis
    which will be linked to the barcode scanning of reagents').
    """

    def __init__(self, batch_id: str, analyst: str, matrix: str):
        self.batch_id = batch_id
        self.analyst = analyst
        self.matrix = matrix
        self.started = datetime.now()
        self.completed: Optional[datetime] = None
        self.steps: list[dict] = []
        self.reagent_scans: list[dict] = []
        self.signoffs: list[dict] = []

    def scan_reagent(self, catalog: ReagentCatalog, raw_barcode: str,
                     step: str = "", **kwargs) -> dict:
        result = catalog.scan(raw_barcode, scanned_by=self.analyst, **kwargs)
        event = {
            "at": datetime.now().isoformat(),
            "step": step,
            **result,
        }
        self.reagent_scans.append(event)
        return result

    def log_step(self, step: str, detail: str = "", value: str = ""):
        """e.g. log_step('Weigh sample', 'Deer Hamburger', '5.02 g')"""
        self.steps.append({
            "at": datetime.now().isoformat(),
            "step": step,
            "detail": detail,
            "value": value,
            "by": self.analyst,
        })

    def sign(self, role: str, initials: str):
        """Analyst / Reviewer / Supervisor sign-off (Summary Sheet signature rows)."""
        self.signoffs.append({
            "role": role,
            "initials": initials,
            "at": datetime.now().isoformat(),
        })
        if role.lower() == "analyst":
            self.completed = datetime.now()

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "analyst": self.analyst,
            "matrix": self.matrix,
            "started": self.started.isoformat(),
            "completed": self.completed.isoformat() if self.completed else None,
            "steps": self.steps,
            "reagent_scans": self.reagent_scans,
            "signoffs": self.signoffs,
        }

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
