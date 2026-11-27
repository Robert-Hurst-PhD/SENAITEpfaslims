"""The chromatogram pages of a report package, drawn from the review traces.

The traces are the raw_traces rows of the worksheet's run in the shared QC
database, read through the add-on's raw_traces.read (the reader Data
Review uses), so a page shows the trace, its edges, its baseline and its
apex as the reviewer left them:

    select(rows, scope, sample_injections, qc_injections)   the scope's rows
    in_run_order(rows, info)             the injections in acquisition order
    paginate(rows) / page_count(rows)    twelve traces to a page, an
                                         injection kept together
    caption(row)                         a trace's analyte, transition, role,
                                         time, area, state and edit
    geometry(row)                        what a cell plots: the peak's span
    draw_page(canvas, page_rows, header, foot) / render(...)   the PDF
    injection_sets / injection_info      the run's injections by sample and
                                         role (injection_results)
    cache_key / cached                   the run's pages kept per worksheet
    pages_for_job(job, scope, db, dir)   what the package build asks for:
                                         the pages and the cache key;
                                         NoTraces when the run stored none

A page is A4 portrait, three columns by four rows; the top 18 mm carry the
page header and the bottom 12 mm stay clear for the package stamp, which
the build draws over every page after assembly. Colours are the print
palette's (print_style.PALETTE). Python 3.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

from .addon import load

PER_PAGE = 12
COLUMNS, ROWS = 3, 4
SCOPES = ("run", "sample_qc", "sample")
NONE_TEXT = "–"
# what the drawing of a page is: a cached page drawn otherwise is not reused
LAYOUT_VERSION = 3
# the span a cell plots: the peak's window and edges, widened either side
# by this share of its width
SPAN_MARGIN = 0.1
# room above the highest point of the span
HEADROOM = 0.08
# the header's smallest type; past it the injections listed are cut short
HEADER_LEAST = 7.0
NO_TRACES = "no stored traces for %s"


class NoTraces(Exception):
    """The worksheet's run stored no traces at all: the message names it."""


# ── selection, pagination, caption (pure) ────────────────────────────────────

def select(rows, scope, sample_injections, qc_injections):
    """The rows a scope draws, in their stored order: `run` every row,
    `sample_qc` the sample's injections, the batch's QC and the run's
    calibration and instrument checks (injection_sets), `sample` the
    sample's only."""
    if scope == "run":
        return list(rows)
    if scope == "sample_qc":
        keep = set(sample_injections) | set(qc_injections)
    elif scope == "sample":
        keep = set(sample_injections)
    else:
        raise ValueError("chromatogram scope must be sample, sample_qc or run, not %r" % (scope,))
    return [r for r in rows if r["injection"] in keep]


def _by_injection(rows):
    groups = []
    for r in rows:
        if groups and groups[-1][0]["injection"] == r["injection"]:
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def paginate(rows, per_page=PER_PAGE):
    """[[row]] a page each. An injection's traces stay together: the next
    injection joins the current page only when it fits there whole, else it
    starts a page. An injection of more than `per_page` traces fills pages
    of its own, and its last page is closed after it."""
    pages, current = [], []
    for group in _by_injection(rows):
        if len(group) > per_page:
            if current:
                pages.append(current)
            pages.extend(group[i:i + per_page] for i in range(0, len(group), per_page))
            current = []
        elif len(current) + len(group) <= per_page:
            current = current + group
        else:
            pages.append(current)
            current = list(group)
    if current:
        pages.append(current)
    return pages


def page_count(rows, per_page=PER_PAGE):
    return len(paginate(rows, per_page))


def in_run_order(rows, info):
    """The rows with their injections in acquisition order, each
    injection's traces together and in their stored order. The sort is
    stable; an injection with no acquisition time keeps its stored place,
    the timed ones taking the other places in time order. `info` is
    injection_info's {injection: (role, acquisition time)}."""
    groups = _by_injection(rows)
    timed = [i for i, g in enumerate(groups) if ((info or {}).get(g[0]["injection"]) or ("", ""))[1]]
    order = sorted(timed, key=lambda i: info[groups[i][0]["injection"]][1])
    placed = list(groups)
    for slot, i in zip(timed, order):
        placed[slot] = groups[i]
    return [r for g in placed for r in g]


def _review():
    return load("raw_review")


def state(peak):
    """The peak's state in Data Review's words (raw_review): the edit's word
    for an applied edit ("re-integrated", "apex chosen"), "Peak deleted",
    "no effect" for an edit kept that the run could not apply, else "auto",
    or "Not detected" for an automatic call with no area."""
    review = _review()
    # the add-on's one reading of a stored peak: auto, edited, deleted or no_effect
    stored = review.stored_state(peak)
    if stored == "deleted" or peak.get("deleted"):
        return review.state_text("", deleted=True)
    if stored == "edited":
        kind = (peak.get("manual") or {}).get("kind")
        return review.EDIT_WORDS.get(kind, kind or "")
    if stored == "no_effect":
        return "no effect"
    return review.STATE_TEXT["nd"] if peak.get("area") is None else "auto"


def _num(value, fmt):
    return NONE_TEXT if value is None else format(float(value), fmt)


def caption(row):
    """"<analyte> · <transition> · <role> · RT <apex> · area <area> · <state>",
    and " · edited by <by> <at>" for a reviewer's edit."""
    peak = row.get("peak") or {}
    text = " · ".join([row.get("analyte") or "", row.get("transition") or "", row.get("role") or "",
                       "RT " + _num(peak.get("apex"), ".2f"), "area " + _num(peak.get("area"), ".0f"),
                       state(peak)])
    manual = peak.get("manual")
    if isinstance(manual, dict):
        text += " · edited by %s %s" % (manual.get("by") or "", manual.get("at") or "")
    return text


def page_header(header, page_rows, info, names=None):
    """The page's header: the run's line, then each injection on the page
    with its role and acquisition time where the run records them, named by
    the lab sample id (`names`, {client sample id: lab sample id};
    sample_names.by_lab_id)."""
    by_lab_id = load("sample_names").by_lab_id
    lines = []
    for group in _by_injection(page_rows):
        name = group[0]["injection"]
        qc_type, acquired = (info or {}).get(name, ("", ""))
        lines.append(" · ".join([by_lab_id(name, names, qc_type)] + ([qc_type] if qc_type else [])
                                + (["acquired " + acquired] if acquired else [])))
    return "\n".join([header] + ["; ".join(lines)])


# ── drawing ──────────────────────────────────────────────────────────────────

_PALETTE = load("print_style").PALETTE
MANUAL_FILL = "s-manual-fill"   # a manually integrated peak's area


def _palette(name, mono=False):
    """A palette colour; every one is ink on a black-and-white page."""
    return colors.HexColor(_PALETTE[INK if mono else name])


TRACE, BASELINE = "tier-c0", "tier-c4"
# a black-and-white page draws everything in ink: the baseline is told from
# the trace by its dashes, the peak's edges by their dots
INK = "print-ink"
EDGE_DASH = (1.2, 1.2)
MONO_BASELINE_DASH = (3.0, 1.5)
TEXT, MUTED, FRAME = "s-body", "s-secondary", "s-border"
PAGE_W, PAGE_H = A4
MARGIN, HEAD, FOOT = 12 * mm, 18 * mm, 12 * mm
CAPTION_SIZE, LABEL_SIZE, CAPTION_LINES = 5.5, 5.0, 3


def _fit_size(text, font, size, width, least=HEADER_LEAST):
    while size > least and stringWidth(text, font, size) > width:
        size -= 0.25
    return size


def _cut_short(entries, font, size, width):
    """The injections' line at `size`: every entry when it fits, else the
    first few and "and N more"."""
    line = "; ".join(entries)
    k = len(entries)
    while k > 1 and stringWidth(line, font, size) > width:
        k -= 1
        line = "; ".join(entries[:k]) + "; and %d more" % (len(entries) - k)
    return line


def _y_at(t, y, x):
    """The trace's intensity at time x, between its stored points."""
    for i in range(1, len(t)):
        if t[i] >= x:
            span = t[i] - t[i - 1]
            return y[i] if not span else y[i - 1] + (y[i] - y[i - 1]) * (x - t[i - 1]) / span
    return y[-1] if y else 0.0


def geometry(row):
    """What a cell plots, in the trace's own units, or None for a trace
    with fewer than two points: "x" the span, the peak's window joined with
    its edges (an edge may lie past the window), widened by SPAN_MARGIN of
    its width either side, within the stored trace, else the whole trace;
    "y" from 0 (or the lowest point) to the highest point in the span or
    baseline level, with HEADROOM above, as Data Review's chart sets its
    axes; "trace" the points drawn (those in the span and one beyond each
    end); "edges" the peak's start and end, "baseline" its two ends,
    "apex" the marked point, each None when the peak has none."""
    t, y = list(row.get("t") or []), list(row.get("y") or [])
    if len(t) < 2 or len(t) != len(y):
        return None
    peak = row.get("peak") or {}
    start, end = peak.get("start"), peak.get("end")
    edges = (start, end) if start is not None and end is not None else None
    bounds = list(peak.get("window") or []) + list(edges or [])
    if bounds:
        lo, hi = min(bounds), max(bounds)
        pad = (hi - lo) * SPAN_MARGIN
        x0, x1 = max(t[0], lo - pad), min(t[-1], hi + pad)
        if not x1 > x0:
            x0, x1 = t[0], t[-1]
    else:
        x0, x1 = t[0], t[-1]
    inside = [i for i, v in enumerate(t) if x0 <= v <= x1]
    first = max((inside[0] if inside else 0) - 1, 0)
    last = min((inside[-1] if inside else len(t) - 1) + 1, len(t) - 1)
    b0, b1 = peak.get("base_start"), peak.get("base_end")
    baseline = ((start, b0), (end, b1)) if edges and b0 is not None and b1 is not None else None
    levels = [y[i] for i in inside] + ([b0, b1] if baseline else [])
    ylo, yhi = min([0.0] + levels), max(levels or [1.0])
    if not yhi > ylo:
        yhi = ylo + 1.0
    yhi += (yhi - ylo) * HEADROOM
    apex = peak.get("apex")
    mark = (apex, _y_at(t, y, apex)) if apex is not None and x0 <= apex <= x1 else None
    return {"x": (x0, x1), "y": (ylo, yhi), "trace": list(zip(t[first:last + 1], y[first:last + 1])),
            "top": max([y[i] for i in inside] or [max(y)]), "edges": edges, "baseline": baseline,
            "apex": mark}


def _draw_trace(c, row, x0, y0, w, h, mono=False):
    """One cell: the injection's name, the plot of geometry(row), and the
    caption under it; `mono`, in ink alone (MONO_BASELINE_DASH)."""
    def _colour(name):
        return _palette(name, mono)
    c.setFillColor(_colour(TEXT))
    c.setFont("Helvetica-Bold", LABEL_SIZE + 0.5)
    c.drawString(x0, y0 + h - 7, row.get("injection") or "")
    # every cell keeps room for CAPTION_LINES under its plot, so the plots
    # of a row line up whatever their captions' length
    lines = simpleSplit(caption(row), "Helvetica", CAPTION_SIZE, w)[:CAPTION_LINES]
    c.setFont("Helvetica", CAPTION_SIZE)
    for i, line in enumerate(lines):
        c.drawString(x0, y0 + 2 + (CAPTION_LINES - 1 - i) * (CAPTION_SIZE + 1), line)
    px, pw = x0 + 2, w - 4
    py = y0 + 4 + CAPTION_LINES * (CAPTION_SIZE + 1) + LABEL_SIZE + 2
    ph = y0 + h - 10 - py
    c.setStrokeColor(_colour(FRAME))
    c.setLineWidth(0.4)
    c.rect(px, py, pw, ph, stroke=1, fill=0)
    g = geometry(row)
    if g is None:
        return
    (t0, t1), (lo, hi) = g["x"], g["y"]

    def X(v):
        return px + (v - t0) / (t1 - t0) * pw

    def Y(v):
        return py + (v - lo) / (hi - lo) * ph

    c.setFillColor(_colour(MUTED))
    c.setFont("Helvetica", LABEL_SIZE)
    c.drawString(px, py - LABEL_SIZE - 1, "%.2f min" % t0)
    c.drawRightString(px + pw, py - LABEL_SIZE - 1, "%.2f min" % t1)
    c.drawString(px + 1.5, py + ph - LABEL_SIZE - 1, "%.3g" % g["top"])
    c.saveState()
    box = c.beginPath()
    box.rect(px, py, pw, ph)
    c.clipPath(box, stroke=0, fill=0)
    if not mono and g["baseline"] and _review().stored_state(row.get("peak")) == "edited":
        # a manually integrated peak: its area down to its baseline, under the trace
        (s0, b0), (s1, b1) = g["baseline"]
        inside = [(a, b) for a, b in zip(row["t"], row["y"]) if s0 <= a <= s1]
        area = c.beginPath()
        area.moveTo(X(s0), Y(b0))
        for a, b in inside:
            area.lineTo(X(a), Y(b))
        area.lineTo(X(s1), Y(b1))
        area.close()
        c.setFillColor(_colour(MANUAL_FILL))
        c.drawPath(area, stroke=0, fill=1)
    path = c.beginPath()
    path.moveTo(X(g["trace"][0][0]), Y(g["trace"][0][1]))
    for a, b in g["trace"][1:]:
        path.lineTo(X(a), Y(b))
    c.setStrokeColor(_colour(TRACE))
    c.setLineWidth(0.5)
    c.drawPath(path, stroke=1, fill=0)
    if g["edges"]:
        c.setStrokeColor(_colour(MUTED))
        c.setLineWidth(0.3)
        c.setDash(*EDGE_DASH)
        for edge in g["edges"]:
            c.line(X(edge), py, X(edge), py + ph)
        c.setDash()
    if g["baseline"]:
        (s0, b0), (s1, b1) = g["baseline"]
        c.setStrokeColor(_colour(BASELINE))
        c.setLineWidth(0.6)
        if mono:
            c.setDash(*MONO_BASELINE_DASH)
        c.line(X(s0), Y(b0), X(s1), Y(b1))
        if mono:
            c.setDash()
    c.restoreState()
    if g["apex"]:
        ax, ay = X(g["apex"][0]), min(Y(g["apex"][1]) + 1.5, py + ph - 3)
        c.setFillColor(_colour(TEXT))
        mark = c.beginPath()
        mark.moveTo(ax, ay)
        mark.lineTo(ax - 1.8, ay + 3)
        mark.lineTo(ax + 1.8, ay + 3)
        mark.close()
        c.drawPath(mark, stroke=0, fill=1)


def draw_page(canvas, page_rows, header, foot, mono=False):
    """One page: the header in the top 18 mm (its first line the run's, the
    second the page's injections separated by "; ", in type no smaller than
    HEADER_LEAST, the first few and "and N more" when they do not fit) and
    up to twelve traces, three across and four down. `foot` is the package's stamp, which the build draws over
    the assembled package: the bottom 12 mm are left clear for it and
    nothing of it is drawn here, so pages kept for a worksheet serve every
    report of the run."""
    width = PAGE_W - 2 * MARGIN
    lines = (header or "").split("\n")
    canvas.setFillColor(_palette(TEXT, mono))
    top = PAGE_H - 8 * mm
    for i, line in enumerate(lines[:2]):
        font = "Helvetica-Bold" if i == 0 else "Helvetica"
        size = _fit_size(line, font, 9.0 if i == 0 else 8.0, width)
        if i == 1:
            line = _cut_short(line.split("; "), font, size, width)
        canvas.setFont(font, size)
        canvas.drawString(MARGIN, top - i * 4.5 * mm, line)
    canvas.setStrokeColor(_palette(FRAME, mono))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, PAGE_H - HEAD + 1.5 * mm, PAGE_W - MARGIN, PAGE_H - HEAD + 1.5 * mm)
    cw = width / COLUMNS
    ch = (PAGE_H - HEAD - FOOT) / ROWS
    for i, row in enumerate(page_rows[:COLUMNS * ROWS]):
        col, line = i % COLUMNS, i // COLUMNS
        _draw_trace(canvas, row, MARGIN + col * cw + 1.5 * mm, PAGE_H - HEAD - (line + 1) * ch + 1 * mm,
                    cw - 3 * mm, ch - 2 * mm, mono)


def render(conn, batch_id, scope, header, foot, sample_injections=(), qc_injections=(), names=None,
           mono=False):
    """(PDF bytes, pages) of the scope's traces of the batch, injections in
    acquisition order (in_run_order); (b"", 0) when the scope holds no
    trace, so nothing blank is ever handed on. Scope `run` reads the whole
    run; the others read only their injections. Every injection is named by
    the lab sample id (`names`, page_header)."""
    rows = select(_read(conn, batch_id, scope, sample_injections, qc_injections), scope,
                  sample_injections, qc_injections)
    info = injection_info(conn, batch_id)
    pages = paginate(in_run_order(rows, info))
    if not pages:
        return b"", 0
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle("Chromatograms · " + (header or batch_id).split("\n")[0])
    for page_rows in pages:
        draw_page(c, page_rows, page_header(header, page_rows, info, names), foot, mono)
        c.showPage()
    c.save()
    return buf.getvalue(), len(pages)


# ── the database and the cache ───────────────────────────────────────────────

def _read(conn, batch_id, scope, sample_injections, qc_injections):
    """The stored traces a scope draws, in stored order: the whole run for
    `run`, else each wanted injection read on its own."""
    rt = load("raw_traces")
    if scope == "run":
        return rt.read(conn, batch_id)
    candidates = [{"injection": n} for n in set(sample_injections) | set(qc_injections)]
    wanted = set(r["injection"] for r in select(candidates, scope, sample_injections, qc_injections))
    stored = conn.execute("SELECT injection, MIN(id) FROM raw_traces WHERE batch_id=? GROUP BY injection",
                          (batch_id,)).fetchall()
    return [r for name, _first in sorted(stored, key=lambda x: x[1]) if name in wanted
            for r in rt.read(conn, batch_id, injection=name)]


def injection_info(conn, batch_id):
    """{injection: (role, acquisition time)} of the batch's injections, as
    the run's processing recorded them in injection_results."""
    out = {}
    for name, qc_type, acquired in conn.execute(
            "SELECT injection_name, qc_type, acquired_at FROM injection_results WHERE batch_id=? ORDER BY id",
            (batch_id,)):
        if name not in out or (not out[name][1] and acquired):
            out[name] = (qc_type or "", acquired or "")
    return out


def method_of(conn, batch_id):
    row = conn.execute("SELECT method FROM injection_results WHERE batch_id=? AND method != '' LIMIT 1",
                       (batch_id,)).fetchone()
    return row[0] if row else ""


def injection_sets(conn, batch_id, sample_ids):
    """(the sample's injections, the batch's QC injections), read from
    injection_results. A sample's injections are those whose name or
    parsed sample id is one of `sample_ids`. The batch's QC are its
    extracted QC and field QC (qc_engine.EXTRACTED_QC_ROLES: blanks,
    fortified blanks, spikes, duplicates) and the calibration standards and
    the instrument's checks the run was judged by (qc_engine.RUN_CHECK_ROLES:
    CAL, ICV, CCV, CCB)."""
    from .qc_engine import EXTRACTED_QC_ROLES, RUN_CHECK_ROLES
    names = set(n for n in sample_ids or () if n)
    sample, qc = set(), set()
    for name, sid, qc_type in conn.execute(
            "SELECT DISTINCT injection_name, sample_id, qc_type FROM injection_results WHERE batch_id=?",
            (batch_id,)):
        if name in names or sid in names:
            sample.add(name)
        if qc_type in EXTRACTED_QC_ROLES or qc_type in RUN_CHECK_ROLES:
            qc.add(name)
    return sample, qc - sample


def cache_key(conn, batch_id, countersign_at, names=None, mono=False):
    """The first 16 hex of the sha256 of the page layout's version, the
    batch's trace rows (each id and creation time, in order), the
    countersign time and the names the injections print by: a new layout,
    new traces, a new countersign or a sample's id changed give a new
    key."""
    h = hashlib.sha256(("layout|%d\n" % LAYOUT_VERSION).encode("utf-8"))
    for rid, created in conn.execute("SELECT id, created_at FROM raw_traces WHERE batch_id=? ORDER BY id",
                                     (batch_id,)):
        h.update(("%s|%s\n" % (rid, created)).encode("utf-8"))
    h.update(("countersign|%s" % (countersign_at or "")).encode("utf-8"))
    h.update(("\nnames|%s" % json.dumps(names or {}, sort_keys=True)).encode("utf-8"))
    if mono:
        # the black-and-white pages are kept apart from the coloured ones
        h.update(b"\nmono")
    return h.hexdigest()[:16]


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def cached(traces_dir, worksheet_id, key, make):
    """The bytes kept as <traces_dir>/<worksheet>-<key>.pdf, made by `make()`
    and kept when there are none yet. The file is written whole (a temporary
    file renamed into place) and the worksheet's pages under another key are
    removed; nothing made is nothing kept."""
    if not _SAFE_ID.match(worksheet_id or ""):
        raise ValueError("not a worksheet id: %r" % (worksheet_id,))
    path = os.path.join(traces_dir, "%s-%s.pdf" % (worksheet_id, key))
    if os.path.isfile(path) and os.path.getsize(path):
        with open(path, "rb") as fh:
            return fh.read()
    data = make()
    if not data:
        return data
    fd, tmp = tempfile.mkstemp(dir=traces_dir, prefix=".building-", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    older = re.compile(re.escape(worksheet_id) + r"-[0-9a-f]+\.pdf\Z")
    for name in os.listdir(traces_dir):
        if older.match(name) and name != os.path.basename(path):
            os.remove(os.path.join(traces_dir, name))
    return data


def _has_traces(conn, batch_id):
    """Whether the run stored any trace."""
    return conn.execute("SELECT 1 FROM raw_traces WHERE batch_id=? LIMIT 1", (batch_id,)).fetchone() is not None


def pages_for_job(job, scope, db_path, traces_dir):
    """(the chromatogram pages of one package job or None when there are
    none to draw, the cache key they were kept under). The run's pages are
    the same for every sample of the worksheet and are kept in `traces_dir`
    under their cache key; a sample's are drawn each time and have no key
    (""). A worksheet whose run stored no traces at all raises NoTraces
    naming it; a sample the run does not hold has no pages (None)."""
    if scope not in SCOPES:
        raise ValueError("chromatogram scope must be sample, sample_qc or run, not %r" % (scope,))
    ws = job.get("worksheet_id") or ""
    if not ws:
        return None, ""
    # every injection named by the lab sample id, never a client's
    names = job.get("sample_names") or {}
    # the client takes its certificates in black and white: the pages too
    mono = bool(job.get("mono"))
    key = ""
    conn = sqlite3.connect("file:%s?mode=ro" % quote(os.path.abspath(db_path)), uri=True)
    try:
        method = method_of(conn, ws)
        header = " · ".join([ws] + ([method] if method else []))
        if scope == "run":
            key = cache_key(conn, ws, job.get("countersign_at") or "", names, mono)
            data = cached(traces_dir, ws, key,
                          lambda: render(conn, ws, "run", header, "", names=names, mono=mono)[0])
        else:
            # a sample's injections are named by its client sample id, the
            # one id the certificate's QC sub-table matches; the SENAITE id
            # is a fallback for a job queued before jobs carried the client id
            sample, qc = injection_sets(conn, ws, [job.get("client_sample_id"), job.get("sample_id")])
            data = render(conn, ws, scope, header, "", sample, qc, names, mono)[0] if sample else b""
        if not data and not _has_traces(conn, ws):
            raise NoTraces(NO_TRACES % ws)
    finally:
        conn.close()
    return data or None, key
