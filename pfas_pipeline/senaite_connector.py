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
  Extraction record    → Attachment on the Worksheet (the sidecar JSON; the
                         reagent lots themselves live in the SENAITE inventory)
  Final report         → ARReport attachment (senaite.impress compatible)
"""

from __future__ import annotations
import json
import mimetypes
import logging
from pathlib import Path
from typing import Optional

import requests

from .models import Batch, QCFlag, SummaryResult

logger = logging.getLogger(__name__)


class SenaiteAPIError(RuntimeError):
    """A senaite.jsonapi call that returned HTTP 200 but did not succeed."""

    def __init__(self, message, path="", payload=None):
        super().__init__(message)
        self.path = path
        self.payload = payload or {}


def _created_uid(res: dict) -> Optional[str]:
    """UID out of a senaite.jsonapi create response.

    The endpoint answers with either {"items": [obj]} or the object itself
    depending on the portal type. Assuming one shape made a SUCCESSFUL
    attachment upload raise KeyError('items'), which the caller then reported
    as a failed push — the file was on the worksheet the whole time.
    """
    items = res.get("items") if isinstance(res, dict) else None
    obj = items[0] if items else res
    return obj.get("uid") if isinstance(obj, dict) else None


# Analysis states whose result a pushed run may write (the core workflow lets
# the result be edited only before submission).
EDITABLE_STATES = ("unassigned", "assigned")
# Sample states a run never writes to (their results are not the reportable ones).
DEAD_SAMPLE_STATES = ("invalid", "cancelled", "rejected")


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
        data = r.json()
        # senaite.jsonapi answers a REFUSED operation with HTTP 200 and
        # {"success": false, "message"...}. raise_for_status() alone is
        # therefore not enough: a delete that the workflow rejected looked like
        # a success, and the caller cheerfully logged that it had removed five
        # attachments that are all still there.
        if isinstance(data, dict) and data.get("success") is False:
            raise SenaiteAPIError(data.get("message") or "operation refused",
                                  path=path, payload=data)
        return data

    def search(self, **query) -> list[dict]:
        out = self._get("search", **query)
        return out.get("items", [])

    # ── Batch ────────────────────────────────────────────────────────────────
    def get_run_manifest(self, batch_id: str, worksheet_id: str = "") -> dict:
        """The worklist the Run Builder planned for this extraction batch (the
        worksheet, asked first), or {}."""
        if not batch_id and not worksheet_id:
            return {}
        params = {"batch_id": batch_id or ""}
        if worksheet_id:
            params["worksheet_id"] = worksheet_id
        try:
            r = self.session.get(f"{self.base}/@@pfas-run-manifest",
                                 params=params,
                                 timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except (requests.HTTPError, requests.ConnectionError, ValueError):
            return {}
        return data if isinstance(data, dict) and "error" not in data else {}

    def get_batch_dilutions(self, batch_id: str, worksheet_id: str = "") -> dict:
        """Dilution map recorded on the extraction batch's FM-ENV-003 log.

        {dilution_injection: {"parent"..., "factor": float}} — empty when the
        batch records none. The logbook is the only source of this
        relationship; the pipeline never infers it from injection names. The
        extraction record lives on the WORKSHEET, which is
        asked for first; a client Batch id is followed to its worksheet.
        """
        if not batch_id and not worksheet_id:
            return {}
        params = {"batch_id": batch_id or ""}
        if worksheet_id:
            params["worksheet_id"] = worksheet_id
        try:
            r = self.session.get(f"{self.base}/@@pfas-batch-dilutions",
                                 params=params,
                                 timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except (requests.HTTPError, requests.ConnectionError, ValueError) as e:
            logger.warning("Could not read the dilution log for %s: %s",
                           batch_id, e)
            return {}
        if not isinstance(data, dict) or "error" in data:
            return {}
        return data

    def find_worksheet(self, worksheet_id: str) -> Optional[dict]:
        """The Worksheet with this id, or None."""
        if not worksheet_id:
            return None
        items = self.search(portal_type="Worksheet", id=worksheet_id)
        return items[0] if items else None

    def find_batch(self, batch_id: str) -> Optional[dict]:
        """An EXISTING Batch by id or title. Deliberately never creates one."""
        if not batch_id:
            return None
        for key in ("id", "title"):
            items = self.search(portal_type="Batch", **{key: batch_id})
            if items:
                return items[0]
        return None

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
        uid = _created_uid(res)
        batch.senaite_batch_uid = uid
        return uid

    # ── Samples (AnalysisRequests) ───────────────────────────────────────────
    def find_sample_by_client_sample_id(self, client_sample_id: str,
                                        batch_uid: str = "") -> Optional[dict]:
        """The sample whose ClientSampleID is exactly *client_sample_id*.

        The injection name an analyst types at the instrument is the client's
        own name for the sample, so this is the natural join between an
        instrument export and a SENAITE sample.

        Scoped to the run's batch, and never an invalid, cancelled or rejected
        sample. It took the first match anywhere: an invalidated sample shares
        its Client Sample ID with its retest, so the run could land on the
        locked original and the retest never got results; and two clients may
        name a sample alike. More than one candidate is
        refused, not guessed (`last_lookup` says why).
        """
        self.last_lookup = ""
        if not client_sample_id:
            return None
        query = {"portal_type": "AnalysisRequest", "getClientSampleID": client_sample_id}
        if batch_uid:
            query["getBatchUID"] = batch_uid
        items = [i for i in self.search(**query)
                 if (i.get("review_state") or "") not in DEAD_SAMPLE_STATES]
        if len(items) > 1:
            self.last_lookup = ("{0} samples have this Client Sample ID{1}: {2}".format(
                len(items), " in the batch" if batch_uid else "",
                ", ".join(sorted(i.get("id") or i.get("uid") or "?" for i in items))))
            return None
        return items[0] if items else None

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
        # what this push did, for the push log (push_log.py)
        self.last_push = {"analysis_uid": "", "value": "", "reason": ""}
        if not analyses:
            logger.debug("No Analysis %s on sample %s",
                         analyte_keyword, sample_uid)
            self.last_push["reason"] = "the sample has no analysis for this analyte"
            return False

        uid = analyses[0]["uid"]
        # A submitted, verified or published result is never overwritten by a
        # reprocess: SENAITE refuses the edit (401), and before this check the
        # refusal aborted the push of every remaining result with a bare
        # "401 Unauthorized". It is retracted in SENAITE
        # first, then the run is uploaded again.
        state = analyses[0].get("review_state") or ""
        if state and state not in EDITABLE_STATES:
            self.last_push = {"analysis_uid": uid, "value": "",
                              "reason": "the analysis is {0}: a reprocess does not overwrite it "
                                        "(retract it in SENAITE first)".format(state)}
            return False
        diluted = bool(result.source_injection
                       and result.source_injection != result.sample_injection)
        if diluted:
            # : the analysis keeps the NEAT, above-LOQ
            # reading; the dilution is appended to it as a retest (created at
            # Data Review submission) with its own result and analysis time.
            payload = {
                "Result": (result.neat_result if result.neat_result is not None
                           else (result.neat_qualifier or "ALoQ")),
                "Remarks": "{0}; reported from dilution {1}".format(
                    result.neat_qualifier or "ALoQ", result.source_injection),
            }
        else:
            payload = {
                "Result": (result.result_ppt
                           if result.result_ppt is not None
                           else result.qualifier),
                "Remarks": " ".join(result.flags) if result.flags else "",
            }
        # Unit and Precision are NOT sent: senaite.jsonapi refuses Precision
        # ("Not allowed to set the field"), and a refused field sinks the whole
        # update, Result included. The add-on sets both inside SENAITE when
        # the analysis changes (analysis_display.py).
        if interims:
            payload["InterimFields"] = [
                {"keyword": k, "value": v} for k, v in interims.items()
            ]
        self._post(f"update/{uid}", payload)
        self.last_push = {"analysis_uid": uid, "value": str(payload["Result"]), "reason": ""}
        if diluted:
            self.push_dilution(uid, result)
        return True

    def push_dilution(self, analysis_uid: str, result: SummaryResult) -> bool:
        """Hand the dilution's result to the add-on, which keeps it on the
        analysis until Data Review submission appends it as a retest."""
        body = {
            "analysis_uid": analysis_uid,
            "result": result.result_ppt,
            "qualifier": result.qualifier or "",
            "flags": list(result.flags or []),
            "factor": result.dilution_factor,
            "injection": result.source_injection,
            "analysed_at": result.analysed_at or "",
            "neat_result": result.neat_result,
            "neat_qualifier": result.neat_qualifier or "",
            "neat_injection": result.sample_injection,
            "neat_analysed_at": result.neat_analysed_at or "",
        }
        try:
            r = self.session.post(f"{self.base}/@@pfas-dilution-result", json=body,
                                  timeout=self.timeout)
            r.raise_for_status()
            ok = bool((r.json() or {}).get("ok"))
        except Exception as exc:                            # noqa: BLE001
            logger.error("dilution for %s not recorded: %s", analysis_uid, exc)
            return False
        if not ok:
            logger.error("dilution for %s refused: %s", analysis_uid, r.text[:200])
        return ok

    def apply_display(self, analysis_uids: list) -> bool:
        """Ask the add-on to set Unit / Precision on the analyses just written
        (analysis_display.py): jsonapi refuses Precision and fires no modified
        event. A failure is logged; the results stand, and SENAITE sets both
        again when the analyses are submitted."""
        if not analysis_uids:
            return True
        try:
            r = self.session.post(f"{self.base}/@@pfas-apply-display",
                                  json={"analysis_uids": list(analysis_uids)}, timeout=self.timeout)
            r.raise_for_status()
            return bool((r.json() or {}).get("ok"))
        except Exception as exc:                            # noqa: BLE001
            logger.error("unit / precision not applied: %s", exc)
            return False

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

        Returns the profile dict ({"vendor"..., "map": {...}, ...}) on success.
        Returns {"error": "..."} when no profile has been saved for this
        vendor_key+version — the importer should refuse and tell the user to open
        Import Studio.

        Raises requests.HTTPError / ConnectionError if SENAITE is unreachable.
        In strict mode, callers do NOT catch this exception —
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

    # ── Extraction log + report attachments ─────────────────────────────────
    def delete_attachments(self, parent_uid: str, label: str) -> int:
        """Remove existing attachments on *parent_uid* carrying *label*.

        Re-importing a run must SUPERSEDE its artefacts, not stack another copy
        beside them — injection_results already replaces its rows, and a
        worksheet holding four identical "Batch Report" PDFs gives the reviewer
        no way to tell which one the current results came from.
        """
        # senaite.jsonapi cannot delete an Attachment, so the add-on exposes an
        # endpoint that can. Falling back to the API path keeps this working
        # against an older add-on, where it will report honestly instead.
        try:
            r = self.session.post(f"{self.base}/@@pfas-retire-attachment",
                                  data={"parent_uid": parent_uid,
                                        "label": label},
                                  timeout=self.timeout)
            if r.status_code == 200:
                retired = (r.json() or {}).get("retired") or []
                if retired:
                    logger.info("Retired %d superseded %r attachment(s)",
                                len(retired), label)
                return len(retired)
            logger.warning("Retire endpoint returned %s; leaving previous "
                           "%r attachment(s) in place", r.status_code, label)
        except (requests.HTTPError, requests.ConnectionError, ValueError) as e:
            logger.warning("Could not retire previous %r attachment(s): %s",
                           label, e)
        return 0

    def attach_file(self, parent_uid: str, file_path: str | Path,
                    label: str = "", replace: bool = True) -> Optional[str]:
        """Upload a file (extraction log JSON, report PDF) as an Attachment."""
        file_path = Path(file_path)
        if not parent_uid:
            logger.error("attach_file(%s): no container given. SENAITE allows "
                         "Attachment only inside a Client or a Worksheet.",
                         file_path.name)
            return None
        if replace and label:
            n = self.delete_attachments(parent_uid, label)
            if n:
                logger.info("Superseded %d previous %r attachment(s)", n, label)
        import base64
        b64 = base64.b64encode(file_path.read_bytes()).decode()
        try:
            # The file field's value must be the base64 STRING itself, with
            # filename alongside it — senaite.jsonapi does
            # `str(value).decode("base64")` and reads filename from the rest of
            # the record. Passing a nested {"data"..., "filename"...} dict
            # stringified the dict and failed with "Incorrect padding", and
            # because the API reports that as HTTP 200 + success:false, every
            # upload looked fine while storing an empty AttachmentFile.obj.
            res = self._post("create", {
                "portal_type": "Attachment",
                "parent_uid": parent_uid,
                "AttachmentFile": b64,
                "filename": file_path.name,
                "content_type": mimetypes.guess_type(file_path.name)[0]
                                or "application/octet-stream",
                "AttachmentKeys": label or file_path.stem,
            })
            return _created_uid(res)
        except requests.HTTPError as e:
            # A 401 here usually is not authentication: senaite.jsonapi returns
            # it for a containment refusal too, and the body says which. The
            # Batch was the wrong container all along — Attachment is permitted
            # only in Client and Worksheet.
            detail = ""
            try:
                detail = e.response.json().get("message", "")
            except Exception:
                pass
            logger.error("Attachment upload failed: %s%s", e,
                         " — " + detail if detail else "")
            return None

    # ── Environmental monitoring ────────────────────────────────────────────
    # `push_sensor_reading()` used to live here, POSTing to an
    # `EnvironmentalReading` Dexterity type. It is removed along with that type:
    # facility monitoring is owned by /data/qc/facility_monitoring.db
    # (facility_qc.temperature_readings), whose columns cover every field the
    # ZODB type declared, so the type was a second store for one fact.
    #
    # It had also never worked, in four independent ways: no caller, a
    # parent_path (/senaite/env-monitoring) that does not exist, field names
    # ("Temperature"/"Humidity") that do not match the schema
    # (temperature_c/humidity_pct), and an `except requests.HTTPError` that
    # logged the whole thing at DEBUG. Any one of those would have been silent.
    #
    # The §6.4 gap this leaves is real and unchanged: facility_units and
    # temperature_readings both still hold zero rows. What is
    # missing is an ingest path into the SQLite store, not a content type.
