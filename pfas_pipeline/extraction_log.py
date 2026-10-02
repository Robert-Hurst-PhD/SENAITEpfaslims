"""The extraction record the batch report prints (pipeline step 6).

What is left of barcode.py after the extraction-ui tablet service and its
JSON reagent catalogue were retired (DECISIONS 2026-10-02 DB1): the SENAITE
guided extraction is the one extraction record and the SENAITE inventory the
one reagent catalogue. GS1 barcode parsing moves to the browser scanner
(docs/BENCH_WORKFLOW_REVIEW.md R9).
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class ExtractionLog:
    """
    The run's extraction record as the batch report prints it: steps, lots
    used, sign-off. Filled from the sidecar the Run Builder writes from the
    SENAITE guided extraction (senaite.pfas.extraction_sidecar).
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
