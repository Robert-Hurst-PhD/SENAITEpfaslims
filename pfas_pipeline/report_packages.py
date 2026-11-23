"""The report package build: the worker's third thread.

A certificate stored at a tier beyond the certificate alone queues one job
file per sample of its report under PFAS_PACKAGE_DIR/queue/
(<report uid>-<sample uid>.json, written whole by the add-on). The worker
builds one package per report from all its samples' jobs:

    queue/ -> building/   while the package is built
           -> done/       after the package was handed back
           -> failed/     after the failure was handed back, or when
                          nothing can be handed back

1. the preconditions from @@pfas-package-source?job=<report uid>: the
   report's package is pending, every sample of the report has its job
   file (else the group waits in queue/), every sample's worksheet is
   verified;
2. each part from @@pfas-package-source?job=&sample=&part=<n>, n indexing
   that sample's job["parts"]; the chromatogram pages from trace_pages_fn;
3. the package: the certificate once, a contents page, the translation
   page (each of the client's samples by the lab sample ID, beside the
   client's own name for it, as the summary gives them: every other part
   names samples by the lab sample ID alone), then each sample's parts in
   its job's order, every page stamped at the foot and a bookmark per part
   (and per sample when the report holds several);
4. the seal: the package sealed with the lab key (esig_seal) as its very
   last write, every page stamped first, " · INTERIM" at the stamp's end
   when the job is an interim certificate's;
5. the hand-back to @@pfas-package-done: ready with the sealed PDF, its
   sha256, the seal certificate's fingerprint and the cache key of the
   chromatogram pages it holds, or failed with the reason.

The package fails closed: the first part that cannot be had fails the whole
package with that part's label and reason, and nothing partial is sent.
When SENAITE cannot be reached, or answers as if the worker were not signed
in (HTTP 401 or 403, or a page where JSON was asked for), the job files go
back to queue/ for the next poll: a fault of the worker's account is not
the package's. Without the seal key the package fails with "Seal key
unavailable" before any part is fetched; a Manager's retry runs it again.

A certificate stored without a package is sealed from its own queue,
PFAS_PACKAGE_DIR/seal/<report uid>.json, by the signing thread
(seal_tick): its stored PDF from @@pfas-seal-source, sealed, handed back
to @@pfas-seal-done; the job file then moves to seal/done, or to
seal/failed with the reason. While SENAITE does not answer it waits in
seal/. Python 3.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import esig_seal
from .addon import load
from .trace_pages import NoTraces

# a label is text, not markup: escaped the one way the add-on escapes it
_escape = load("html_text").escape

log = logging.getLogger("pfas_pipeline.report_packages")

SOURCE_VIEW = "@@pfas-package-source"
DONE_VIEW = "@@pfas-package-done"
SEAL_SOURCE_VIEW = "@@pfas-seal-source"
SEAL_DONE_VIEW = "@@pfas-seal-done"
# the certificate seal queue under PFAS_PACKAGE_DIR, and where its jobs settle
SEAL_DIR = "seal"
SEAL_SETTLED = ("done", "failed")
# the worker's folders under PFAS_PACKAGE_DIR; the add-on writes queue/ and
# reads queue/ and building/ to know a report is still being built
SUBDIRS = ("queue", "building", "done", "failed", "traces")
DIR_MODE = 0o770
WORKER = "pfas-worker"
# parts the worker draws itself: the source view serves nothing for them
GENERATED = ("contents", "chromatograms")
HAND_BACK_TIMEOUT = 300

NOT_VERIFIED = "The worksheet is not verified"
NOT_HELD = "The report does not hold sample %s"
TIMED_OUT = "timed out"
NOT_AVAILABLE = "not available"
NOT_A_PDF = "not a PDF"
NO_PAGES = "the PDF has no pages"
REFUSED = "The package was refused: %s"
NOT_BUILT = "The package could not be built: %s"
NO_PARTS = "no parts"
NO_CERTIFICATE = "no certificate part"
NO_TRANSLATION = "no sample names were given for the translation page"
# the translation page: the client's own sample names beside the lab's IDs
NAMES_PART = {"key": "sample_names", "label": "Sample names"}
NAMES_TITLE = "Sample names"
NAMES_TEXT = ("This package names every sample by the laboratory's sample ID. "
              "Your own name for each sample is beside it.")
NAMES_HEAD = ("Laboratory sample ID", "Your sample name")
NO_NAME = "\u2014"
MISSING = "Job files missing for samples: %s"
TWICE = "Two job files name sample %s"
DISAGREE = "Job files disagree on design revisions: %s"
SEAL_REFUSED = "The seal was refused: %s"
NOT_SEALED = "The certificate could not be sealed: %s"
CERTIFICATE = "Certificate"
INTERIM = " · INTERIM"

STAMP_SIZE = 8
STAMP_RISE = 6 * mm

_styles = getSampleStyleSheet()
_H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontSize=16)
_ROW = ParagraphStyle("Row", parent=_styles["BodyText"], fontSize=10, leading=13)
_CONTENTS = TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
])
# a black-and-white package (a client who takes its certificates so): its
# rules and its stamp in ink
_CONTENTS_MONO = TableStyle(list(_CONTENTS.getCommands())[:-1] + [
    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.black),
])
STAMP_GREY = colors.Color(0.25, 0.25, 0.25)


def _table_style(mono):
    return _CONTENTS_MONO if mono else _CONTENTS


class BuildFailed(Exception):
    """The package cannot be built; the message is the reason handed back."""


class PartError(BuildFailed):
    """A part cannot be had: "<part label>: <reason>"."""

    def __init__(self, label, reason):
        self.label, self.reason = label, reason
        super().__init__(f"{label}: {reason}")


class Unreachable(Exception):
    """SENAITE did not answer; the job is tried again at the next poll."""


class SignInFault(Unreachable):
    """SENAITE answered, but not to the worker's account: a sign-in page or
    a refused permission. The job is tried again at the next poll; the
    account is what to put right."""


class HandBackRefused(Exception):
    """The done view refused the hand-back; the message is its error."""


# ── the queue ────────────────────────────────────────────────────────────────

def ensure_dirs(package_dir):
    """The worker's folders, made when absent, group-writable for SENAITE
    (both run as the same uid)."""
    for d in [package_dir] + [os.path.join(package_dir, s) for s in SUBDIRS]:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            os.chmod(d, DIR_MODE)


def _move(paths, package_dir, sub):
    """The files moved, same names, into package_dir/sub; their new paths."""
    out = []
    for p in paths:
        dest = os.path.join(package_dir, sub, os.path.basename(p))
        os.replace(p, dest)
        out.append(dest)
    return out


def recover(package_dir):
    """A build cut short (the worker stopped) is queued again."""
    building = os.path.join(package_dir, "building")
    names = sorted(os.listdir(building))
    _move([os.path.join(building, n) for n in names], package_dir, "queue")
    if names:
        log.warning("report packages: %d job file(s) left building were queued again", len(names))


def read_jobs(queue_dir):
    """[(path, job)] of the job files in queue_dir, oldest queued first. A
    file being written has another name and is not read; one that does not
    parse is set aside in failed/ so it neither blocks a retry nor is read
    again."""
    jobs = []
    for name in sorted(os.listdir(queue_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(queue_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                job = json.load(fh)
            if not isinstance(job, dict) or not job.get("report_uid"):
                raise ValueError("not a job")
        except (OSError, ValueError) as exc:
            log.error("report packages: job file %s cannot be read (%s): set aside", name, exc)
            _move([path], os.path.dirname(queue_dir), "failed")
            continue
        jobs.append((path, job))
    jobs.sort(key=lambda pj: (pj[1].get("queued_at") or "", os.path.basename(pj[0])))
    return jobs


def group_by_report(jobs):
    """One group per report, in the order of each report's oldest job."""
    groups = {}
    for path, job in jobs:
        groups.setdefault(job["report_uid"], []).append((path, job))
    return list(groups.values())


# ── talking to SENAITE ───────────────────────────────────────────────────────

def _check(now, deadline):
    if deadline is not None and now() > deadline:
        raise BuildFailed(TIMED_OUT)


def _left(now, deadline, most=60.0):
    """A request's timeout: the time left to the deadline, at least 1 s."""
    return most if deadline is None else max(1.0, deadline - now())


def _source_url(base_url, **params):
    return f"{base_url.rstrip('/')}/{SOURCE_VIEW}?{urlencode(params)}"


def _done_url(base_url, view=DONE_VIEW):
    return f"{base_url.rstrip('/')}/{view}"


def _get(session, url, timeout):
    try:
        return session.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise Unreachable(f"{url}: {exc}") from exc


# what SENAITE answers a caller it does not take as signed in or allowed
SIGN_IN_STATUSES = (401, 403)
SIGN_IN = "%s answered HTTP %s: check the worker's SENAITE account"
NOT_JSON = "%s answered a page, not JSON: check the worker's SENAITE account"


def _signed_in(resp, view):
    """SignInFault when the answer is a sign-in or permission refusal."""
    if resp.status_code in SIGN_IN_STATUSES:
        raise SignInFault(SIGN_IN % (view, resp.status_code))


def _error(resp):
    """The view's {"error"} text, None when the answer carries none."""
    try:
        body = resp.json()
    except ValueError:
        return None
    return body.get("error") if isinstance(body, dict) else None


def fetch_summary(session, base_url, report_uid, now=time.monotonic, deadline=None):
    """The report's preconditions. Unreachable when SENAITE does not answer
    or answers a server error; SignInFault when it answers a sign-in or
    permission refusal, or a page rather than JSON; BuildFailed when it
    refuses."""
    resp = _get(session, _source_url(base_url, job=report_uid), _left(now, deadline))
    if resp.status_code >= 500:
        raise Unreachable(f"{SOURCE_VIEW} answered HTTP {resp.status_code}")
    _signed_in(resp, SOURCE_VIEW)
    if resp.status_code != 200:
        raise BuildFailed(_error(resp) or f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise SignInFault(NOT_JSON % SOURCE_VIEW) from None
    if not isinstance(body, dict) or not body.get("ok"):
        raise BuildFailed(f"{SOURCE_VIEW} answered no summary")
    return body


def _label(part):
    return part.get("label") or part.get("key")


def _refusal(part, resp):
    """The PartError for a part the view did not serve. Its 409 already
    reads "<label>: <reason>", kept as it is."""
    label = _label(part)
    error = _error(resp)
    if not error:
        return PartError(label, f"HTTP {resp.status_code}")
    prefix = f"{label}: "
    return PartError(label, error[len(prefix):] if error.startswith(prefix) else error)


def fetch_parts(session, base_url, job, skip=(), now=time.monotonic, deadline=None):
    """[(part, bytes)] in job["parts"] order for the parts the source view
    serves (not the generated ones, nor any key in `skip`); the first part
    not served raises PartError, and the deadline is checked before each."""
    out = []
    for n, part in enumerate(job.get("parts") or []):
        if part.get("key") in GENERATED or part.get("key") in skip:
            continue
        _check(now, deadline)
        url = _source_url(base_url, job=job["report_uid"], sample=job["sample_uid"], part=n)
        resp = _get(session, url, _left(now, deadline))
        if resp.status_code != 200:
            _signed_in(resp, SOURCE_VIEW)
            raise _refusal(part, resp)
        out.append((part, resp.content))
    return out


def post_done(session, base_url, jobs, pdf, pages, revisions, worker, trace_key, cert_fp=""):
    """The built package handed back for the report, each field once: the
    sha256 is of the sealed bytes sent, cert_fp names the seal's
    certificate."""
    first = jobs[0]
    data = {"job": first["report_uid"], "state": "ready",
            "sha256": hashlib.sha256(pdf).hexdigest(), "pages": str(pages),
            "revisions": json.dumps(revisions, sort_keys=True), "worker": worker,
            "trace_key": trace_key, "cert_fp": cert_fp}
    files = {"pdf": (f"{first.get('report_id') or first['report_uid']}.pdf", pdf, "application/pdf")}
    _hand_back(session, base_url, data, files)


def post_failed(session, base_url, jobs, reason):
    """The report's package failed, with the reason for whoever retries it."""
    _hand_back(session, base_url, {"job": jobs[0]["report_uid"], "state": "failed", "reason": reason})


def _hand_back(session, base_url, data, files=None, view=DONE_VIEW):
    try:
        resp = session.post(_done_url(base_url, view), data=data, files=files, timeout=HAND_BACK_TIMEOUT)
    except requests.RequestException as exc:
        raise Unreachable(f"{view}: {exc}") from exc
    if resp.status_code >= 500:
        raise Unreachable(f"{view} answered HTTP {resp.status_code}")
    _signed_in(resp, view)
    if resp.status_code != 200:
        raise HandBackRefused(_error(resp) or f"HTTP {resp.status_code}")
    # only the view's own {"ok": true} is a hand-back taken: a sign-in page
    # or a redirect answering 200 stored nothing, and is tried again
    try:
        body = resp.json()
    except ValueError:
        raise SignInFault(NOT_JSON % view) from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise HandBackRefused(f"{view} did not confirm the hand-back")


# ── the assembly (pure: bytes in, bytes out) ─────────────────────────────────

def stamp_text(report_id, revision, tier_name, i, n, interim=False):
    """The foot of every page; an interim certificate's package says so at
    its end."""
    text = f"{report_id} · revision {revision} · {tier_name} · page {i} of {n}"
    return text + INTERIM if interim else text


def _row_label(part):
    sample = part.get("sample_id")
    return f"{sample} · {_label(part)}" if sample else _label(part)


def contents_rows(parts_with_first_page):
    """[(label, first page)] for the contents page; the contents page does
    not list itself."""
    return [(_row_label(part), page) for part, page in parts_with_first_page
            if part.get("key") != "contents"]


def _contents_pdf(rows, mono=False):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Contents",
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    table = Table([[Paragraph(_escape(label), _ROW), str(page)] for label, page in rows],
                  colWidths=[doc.width - 25 * mm, 25 * mm])
    table.setStyle(_table_style(mono))
    doc.build([Paragraph("Contents", _H1), Spacer(1, 4 * mm), table])
    return buf.getvalue()


def names_rows(translation):
    """The translation page's rows, [(lab sample ID, the client's own
    name)], from the summary's [{"sample_id", "client_sample_id"}]; a
    sample with no name of the client's reads NO_NAME."""
    return [((t.get("sample_id") or ""), (t.get("client_sample_id") or "").strip() or NO_NAME)
            for t in translation or [] if isinstance(t, dict)]


def _names_pdf(rows, mono=False):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=NAMES_TITLE,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    data = [[Paragraph("<b>%s</b>" % _escape(h), _ROW) for h in NAMES_HEAD]]
    data += [[Paragraph(_escape(lab), _ROW), Paragraph(_escape(own), _ROW)] for lab, own in rows]
    table = Table(data, colWidths=[doc.width / 2, doc.width / 2], repeatRows=1)
    table.setStyle(_table_style(mono))
    doc.build([Paragraph(NAMES_TITLE, _H1), Paragraph(_escape(NAMES_TEXT), _ROW), Spacer(1, 4 * mm), table])
    return buf.getvalue()


def _reader(part, data):
    label = _label(part)
    if not data:
        raise PartError(label, NOT_AVAILABLE)
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PartError(label, NOT_A_PDF)
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = len(reader.pages)
    except Exception as exc:                                # noqa: BLE001
        raise PartError(label, f"{NOT_A_PDF}: {exc}") from exc
    if not pages:
        raise PartError(label, NO_PAGES)
    return reader


def _laid_out(readers, mono=False):
    """The contents PDF and each part's first page (1-based). The contents
    page count moves every later part, so it is laid out until it holds."""
    k = 1
    while True:
        firsts, page = [], 1
        for part, reader in readers:
            firsts.append((part, page))
            page += k if reader is None else len(reader.pages)
        contents = PdfReader(io.BytesIO(_contents_pdf(contents_rows(firsts), mono)))
        if len(contents.pages) == k:
            return contents, firsts
        k = len(contents.pages)


def _stamp(writer, stamp):
    """Every page gets the stamp at its foot centre, drawn on an overlay
    the size of that page; the page's own content is not redrawn. `stamp`
    is (report id, revision, tier name[, interim[, mono]])."""
    report_id, revision, tier_name = stamp[:3]
    interim = bool(stamp[3]) if len(stamp) > 3 else False
    mono = bool(stamp[4]) if len(stamp) > 4 else False
    n = len(writer.pages)
    for page in writer.pages:
        if page.get("/Rotate"):
            page.transfer_rotation_to_content()
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, page in enumerate(writer.pages, 1):
        box = page.cropbox
        left, bottom = float(box.left), float(box.bottom)
        c.setPageSize((left + float(box.width), bottom + float(box.height)))
        c.setFont("Helvetica", STAMP_SIZE)
        c.setFillColor(colors.black if mono else STAMP_GREY)
        c.drawCentredString(left + float(box.width) / 2, bottom + STAMP_RISE,
                            stamp_text(report_id, revision, tier_name, i, n, interim))
        c.showPage()
    c.save()
    overlay = PdfReader(io.BytesIO(buf.getvalue()))
    for page, over in zip(writer.pages, overlay.pages):
        page.merge_page(over)


def assemble(parts, generated, stamp):
    """(PDF bytes, page count) of the package: `parts` are (part, PDF bytes)
    in package order, a part without bytes taken from `generated` by its key;
    the contents part is drawn here. Every page is stamped; a bookmark marks
    each part's first page, under its sample's bookmark when the part names
    a sample_id."""
    if not parts:
        raise BuildFailed(NO_PARTS)
    readers = [(part, None if part.get("key") == "contents"
                else _reader(part, data if data is not None else generated.get(part.get("key"))))
               for part, data in parts]
    contents, firsts = _laid_out(readers, bool(stamp[4]) if len(stamp) > 4 else False)
    writer = PdfWriter()
    samples = {}
    for (part, reader), (_p, first) in zip(readers, firsts):
        writer.append(reader if reader is not None else contents, import_outline=False)
        sample = part.get("sample_id")
        parent = None
        if sample:
            if sample not in samples:
                samples[sample] = writer.add_outline_item(sample, first - 1)
            parent = samples[sample]
        writer.add_outline_item(_label(part), first - 1, parent=parent)
    _stamp(writer, stamp)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), len(writer.pages)


# ── one report's build ───────────────────────────────────────────────────────

def build(jobs, session, base_url, trace_pages_fn, now=time.monotonic, deadline=None, signer=None,
          translation=None):
    """(sealed PDF bytes, pages, revisions, trace key) for one report from
    its samples' jobs: the certificate once (from the first job), one
    contents page, the translation page from `translation` (the summary's
    rows; None fails the package), then each sample's parts in its job's
    order, stamped, then sealed with `signer` as the last write. `trace_pages_fn(job,
    scope)` draws a chromatograms part as (bytes, cache key); None or no
    bytes fails the package. The revisions are the design revisions the job
    files name; the trace key is each cache key the pages were kept under,
    once, in the order drawn, joined by commas ("" when none). With no
    signer, or one whose certificate is out of date, SealUnavailable with
    the reason before anything is fetched."""
    esig_seal.require(signer)
    revisions = design_revisions(jobs)
    first = jobs[0]
    if not all(j.get("parts") for j in jobs):
        raise BuildFailed(NO_PARTS)
    if not [p for p in first["parts"] if p.get("key") == "certificate"]:
        raise BuildFailed(NO_CERTIFICATE)
    if translation is None:
        raise BuildFailed(NO_TRANSLATION)
    many = len(jobs) > 1
    others = [p.get("key") for p in first["parts"] if p.get("key") != "certificate"]
    certificate = fetch_parts(session, base_url, first, skip=others, now=now, deadline=deadline)
    parts = certificate + [(p, None) for p in first["parts"] if p.get("key") == "contents"]
    # every package carries the translation page, after the contents
    # the client takes its certificates in black and white: every page
    mono = bool(first.get("mono"))
    parts.append((dict(NAMES_PART), _names_pdf(names_rows(translation), mono)))
    keys = []
    for job in jobs:
        served = iter(fetch_parts(session, base_url, job, skip=("certificate",), now=now, deadline=deadline))
        for part in job["parts"]:
            key = part.get("key")
            if key in ("certificate", "contents"):
                continue
            if key == "chromatograms":
                data, trace_key = _trace_pages(trace_pages_fn, job, part, now, deadline)
                if trace_key and trace_key not in keys:
                    keys.append(trace_key)
            else:
                data = next(served)[1]
            parts.append((dict(part, sample_id=job.get("sample_id")) if many else part, data))
    _check(now, deadline)
    stamp = (first.get("report_id"), first.get("revision"), first.get("tier_name"), bool(first.get("interim")),
             mono)
    pdf, pages = assemble(parts, {}, stamp)
    _check(now, deadline)
    # the seal is the package's last write: nothing changes the bytes after it
    sealed = esig_seal.seal_pdf(pdf, signer, esig_seal.seal_name(first.get("lab_name")),
                                esig_seal.seal_reason(first.get("report_id"), first.get("revision")))
    return sealed, pages, revisions, ",".join(keys)


def design_revisions(jobs):
    """The design revisions the report's job files name, read from the files
    themselves. The package prints from one revision of each design, so job
    files that name different ones fail it."""
    kinds = sorted(set(k for j in jobs for k in (j.get("design_revisions") or {})))
    named = [j.get("design_revisions") or {} for j in jobs]
    differ = [k for k in kinds if len(set(json.dumps(n.get(k)) for n in named)) > 1]
    if differ:
        raise BuildFailed(DISAGREE % ", ".join(differ))
    return dict((k, named[0][k]) for k in kinds)


def _trace_pages(trace_pages_fn, job, part, now, deadline):
    _check(now, deadline)
    try:
        data, key = trace_pages_fn(job, part.get("scope"))
    except BuildFailed:
        raise
    except NoTraces as exc:
        # nothing to draw, and the reason names the worksheet
        raise PartError(_label(part), str(exc)) from exc
    except Exception as exc:                                # noqa: BLE001
        log.exception("chromatogram pages failed for %s", job.get("sample_id"))
        raise PartError(_label(part), str(exc) or type(exc).__name__) from exc
    _check(now, deadline)
    if not data:
        raise PartError(_label(part), NOT_AVAILABLE)
    return data, key or ""


def _utcnow():
    return datetime.now(timezone.utc)


def _queued_at(job):
    """When the job was queued (the add-on stamps UTC), None when it cannot
    be read."""
    try:
        at = datetime.fromisoformat(job.get("queued_at") or "")
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def overdue(jobs, timeout, clock=_utcnow):
    """Whether the report's oldest job was queued more than `timeout`
    seconds ago; a job whose time cannot be read counts as overdue, so it
    is never waited on for ever."""
    times = [_queued_at(j) for j in jobs]
    if not times or None in times:
        return True
    return (clock() - min(times)).total_seconds() > timeout


class _Group:
    """One report's job files while the worker holds them in building/."""

    def __init__(self, group, session, base_url, overdue):
        self.package_dir = os.path.dirname(os.path.dirname(group[0][0]))
        self.jobs = [j for _p, j in group]
        self.report_uid = self.jobs[0]["report_uid"]
        self.session, self.base_url, self.overdue = session, base_url, overdue
        self.paths = _move([p for p, _j in group], self.package_dir, "building")

    def settle(self, sub, outcome):
        _move(self.paths, self.package_dir, sub)
        return outcome

    def again(self, exc):
        """SENAITE did not answer: queued again for the next poll, unless the
        report has been queued past the build timeout; then it is set aside
        for a Manager's retry rather than rebuilt for ever."""
        if self.overdue:
            log.error("report package %s set aside: %s, and it was queued past the build timeout",
                      self.report_uid, exc)
            return self.settle("failed", "failed")
        # the worker's own account is at fault: someone has to act on it
        level = logging.ERROR if isinstance(exc, SignInFault) else logging.WARNING
        log.log(level, "report package %s: %s; queued again", self.report_uid, exc)
        return self.settle("queue", "waiting")

    def fail(self, reason):
        log.warning("report package %s failed: %s", self.report_uid, reason)
        try:
            post_failed(self.session, self.base_url, self.jobs, reason)
        except Unreachable as exc:
            return self.again(exc)
        except HandBackRefused as exc:
            log.error("report package %s: the failure was refused: %s", self.report_uid, exc)
        except Exception:                                   # noqa: BLE001
            log.exception("report package %s: the failure could not be handed back", self.report_uid)
        return self.settle("failed", "failed")


def _missing(held, uids, summary):
    """The sample ids of the report's samples that have no job file."""
    jobs = summary.get("jobs") or {}
    return [(jobs.get(u) or {}).get("sample_id") or u for u in held if u not in uids]


def process(group, session, base_url, trace_pages_fn, timeout, now=time.monotonic, clock=_utcnow, signer=None):
    """Build, seal with `signer` and hand back one report's package from
    its group of job files: "done", "failed", or "waiting" (the files back
    in queue/: a sample's job file is still to come, or SENAITE did not
    answer). `now` is the build's clock (the deadline), `clock` the wall
    clock the jobs' queued_at is read against. No signer fails the package
    with "Seal key unavailable". Whatever goes wrong after the files are
    taken, they are settled: none is left in building/."""
    g = _Group(group, session, base_url, overdue([j for _p, j in group], timeout, clock))
    try:
        return _process(g, trace_pages_fn, timeout, now, signer)
    except Exception as exc:                                # noqa: BLE001
        log.exception("report package %s could not be built", g.report_uid)
        return g.fail(NOT_BUILT % (str(exc) or type(exc).__name__))


def _process(g, trace_pages_fn, timeout, now, signer):
    deadline = now() + timeout
    try:
        summary = fetch_summary(g.session, g.base_url, g.report_uid, now, deadline)
    except Unreachable as exc:
        return g.again(exc)
    except BuildFailed as exc:
        # refused before any part was fetched: the failure is still handed
        # back, so the record carries the reason; a report that is gone
        # refuses it too and the files are set aside
        return g.fail(str(exc))
    state = summary.get("state")
    if state == "ready":
        # built and handed back before; only the confirmation was lost
        log.warning("report package %s is ready already: its job files are done", g.report_uid)
        return g.settle("done", "done")
    if state != "pending":
        log.error("report package %s set aside: the package is %s, not pending", g.report_uid, state)
        return g.settle("failed", "failed")
    held = list(summary.get("samples") or [])
    uids = [j["sample_uid"] for j in g.jobs]
    stray = [j for j in g.jobs if j["sample_uid"] not in held]
    if stray:
        return g.fail(NOT_HELD % (stray[0].get("sample_id") or stray[0]["sample_uid"]))
    twice = [j for i, j in enumerate(g.jobs) if j["sample_uid"] in uids[:i]]
    if twice:
        return g.fail(TWICE % (twice[0].get("sample_id") or twice[0]["sample_uid"]))
    if sorted(uids) != sorted(held):
        if g.overdue:
            return g.fail(MISSING % ", ".join(_missing(held, uids, summary)))
        return g.settle("queue", "waiting")
    jobs = sorted(g.jobs, key=lambda j: held.index(j["sample_uid"]))
    verified = summary.get("worksheet_verified") or {}
    if not all(verified.get(j["sample_uid"]) is True for j in jobs):
        return g.fail(NOT_VERIFIED)
    # each sample's run's names as SENAITE gives them now: the chromatogram
    # pages name every injection by the lab sample id (trace_pages)
    names = summary.get("sample_names") or {}
    jobs = [dict(j, sample_names=names.get(j["sample_uid"]) or {}) for j in jobs]
    try:
        pdf, pages, revisions, trace_key = build(jobs, g.session, g.base_url, trace_pages_fn, now, deadline,
                                                 signer, translation=summary.get("translation"))
        _check(now, deadline)
    except Unreachable as exc:
        return g.again(exc)
    except (BuildFailed, esig_seal.SealUnavailable) as exc:
        return g.fail(str(exc))
    try:
        post_done(g.session, g.base_url, jobs, pdf, pages, revisions, WORKER, trace_key,
                  esig_seal.cert_fp(signer))
    except Unreachable as exc:
        return g.again(exc)
    except HandBackRefused as exc:
        return g.fail(REFUSED % exc)
    log.info("report package %s ready: %d pages", g.report_uid, pages)
    return g.settle("done", "done")


def tick(package_dir, session, base_url, trace_pages_fn, timeout, signer_fn=esig_seal.signer_from_env):
    """One poll: every report whose job files are queued, oldest first,
    sealed with the key read once for the poll (only when a package
    waits)."""
    groups = group_by_report(read_jobs(os.path.join(package_dir, "queue")))
    signer = signer_fn() if groups else None
    why = esig_seal.unusable(signer) if signer is not None else None
    if why:
        log.warning(why)
    for group in groups:
        try:
            process(group, session, base_url, trace_pages_fn, timeout, signer=signer)
        except Exception:                                   # noqa: BLE001
            log.exception("report package %s failed", group[0][1].get("report_uid"))


def thread_session(senaite):
    """A session of the package thread's own, signed in as the connector's:
    a requests.Session is not shared between threads."""
    session = requests.Session()
    session.auth = senaite.session.auth
    return session


def loop(package_dir, senaite, every, trace_pages_fn, timeout, signer_fn=esig_seal.signer_from_env):
    """The worker's package thread: the folders made and a cut-short build
    queued again once, then a poll every `every` seconds."""
    session = thread_session(senaite)
    log.info("Package queue %s (every %ss)", package_dir, every)
    started = False
    while True:
        try:
            if not started:
                ensure_dirs(package_dir)
                recover(package_dir)
                started = True
            tick(package_dir, session, senaite.base, trace_pages_fn, timeout, signer_fn)
        except Exception:                                   # noqa: BLE001
            log.exception("report package poll failed")
        time.sleep(every)


# ── the certificate seal queue (the signing thread's) ────────────────────────

def _seal_dirs(package_dir):
    seal_dir = os.path.join(package_dir, SEAL_DIR)
    for d in [seal_dir] + [os.path.join(seal_dir, s) for s in SEAL_SETTLED]:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            os.chmod(d, DIR_MODE)
    return seal_dir


def read_seal_jobs(seal_dir):
    """[(path, job)] of the seal jobs waiting, oldest queued first; one
    that cannot be read is set aside in seal/failed."""
    jobs = []
    for name in sorted(os.listdir(seal_dir)):
        path = os.path.join(seal_dir, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                job = json.load(fh)
            if not isinstance(job, dict) or not job.get("report"):
                raise ValueError("not a seal job")
        except (OSError, ValueError) as exc:
            log.error("certificate seal: job file %s cannot be read (%s): set aside", name, exc)
            os.replace(path, os.path.join(seal_dir, "failed", name))
            continue
        jobs.append((path, job))
    jobs.sort(key=lambda pj: (pj[1].get("queued_at") or "", os.path.basename(pj[0])))
    return jobs


def _settle_seal(path, job, sub, reason=None):
    """The job file moved to seal/<sub>; a failed one keeps its reason."""
    dest = os.path.join(os.path.dirname(path), sub, os.path.basename(path))
    if reason is None:
        os.replace(path, dest)
        return
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dict(job, reason=reason, failed_at=_utcnow().replace(microsecond=0).isoformat()),
                  fh, sort_keys=True, indent=2)
    os.replace(tmp, dest)
    os.remove(path)


def _seal_failed(path, job, session, base_url, reason):
    """The failure handed back, so the report shows it and publishing
    waits for a Manager's retry; the job set aside with the reason. While
    SENAITE does not answer the job waits."""
    log.warning("certificate seal %s failed: %s", job["report"], reason)
    try:
        _hand_back(session, base_url, {"report": job["report"], "state": "failed", "reason": reason},
                   view=SEAL_DONE_VIEW)
    except Unreachable as exc:
        log.warning("certificate seal %s: %s; queued again", job["report"], exc)
        return "waiting"
    except HandBackRefused as exc:
        log.error("certificate seal %s: the failure was refused: %s", job["report"], exc)
    _settle_seal(path, job, "failed", reason)
    return "failed"


def seal_job(path, job, session, base_url, signer):
    """Seal one stored certificate and hand it back: "done", "failed", or
    "waiting" (left in seal/ for the next poll)."""
    report = job["report"]
    why = esig_seal.unusable(signer)
    if why:
        return _seal_failed(path, job, session, base_url, why)
    resp = None
    try:
        resp = _get(session, f"{base_url.rstrip('/')}/{SEAL_SOURCE_VIEW}?{urlencode({'report': report})}", 60)
        if resp.status_code >= 500:
            raise Unreachable(f"{SEAL_SOURCE_VIEW} answered HTTP {resp.status_code}")
        _signed_in(resp, SEAL_SOURCE_VIEW)
    except Unreachable as exc:
        level = logging.ERROR if isinstance(exc, SignInFault) else logging.WARNING
        log.log(level, "certificate seal %s: %s; queued again", report, exc)
        return "waiting"
    if resp.status_code != 200:
        # the report no longer waits for a seal: nothing to hand back
        reason = _error(resp) or f"HTTP {resp.status_code}"
        log.error("certificate seal %s set aside: %s", report, reason)
        _settle_seal(path, job, "failed", reason)
        return "failed"
    data = resp.content or b""
    if not data.lstrip()[:5].startswith(b"%PDF"):
        return _seal_failed(path, job, session, base_url, f"{CERTIFICATE}: {NOT_A_PDF}")
    try:
        sealed = esig_seal.seal_pdf(data, signer, esig_seal.seal_name(job.get("lab_name")),
                                    esig_seal.seal_reason(job.get("report_id") or report, job.get("revision")))
    except Exception as exc:                                # noqa: BLE001
        log.exception("certificate seal %s could not be made", report)
        return _seal_failed(path, job, session, base_url, NOT_SEALED % (str(exc) or type(exc).__name__))
    fields = {"report": report, "state": "sealed", "sha256": hashlib.sha256(sealed).hexdigest(),
              "cert_fp": esig_seal.cert_fp(signer)}
    files = {"pdf": (f"{job.get('report_id') or report}.pdf", sealed, "application/pdf")}
    try:
        _hand_back(session, base_url, fields, files, view=SEAL_DONE_VIEW)
    except Unreachable as exc:
        log.warning("certificate seal %s: %s; queued again", report, exc)
        return "waiting"
    except HandBackRefused as exc:
        reason = SEAL_REFUSED % exc
        log.error("certificate seal %s: %s", report, reason)
        _settle_seal(path, job, "failed", reason)
        return "failed"
    log.info("certificate %s sealed", job.get("report_id") or report)
    _settle_seal(path, job, "done")
    return "done"


def seal_tick(package_dir, session, base_url, signer):
    """One poll of the certificate seal queue, oldest first."""
    seal_dir = _seal_dirs(package_dir)
    for path, job in read_seal_jobs(seal_dir):
        try:
            seal_job(path, job, session, base_url, signer)
        except Exception:                                   # noqa: BLE001
            log.exception("certificate seal %s failed", job.get("report"))
