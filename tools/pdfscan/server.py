"""senaite.pfas report scanner: the text of each page of a PDF.

    GET  /health   -> {"ok": true, "pdfminer": "<version>"}
    POST /text     <pdf bytes> -> {"pages": ["text of page 1", ...]}

SENAITE scans an instrument report when it is uploaded, to find the pages
carrying the lab's manual-integration heading (manual_integration.py decides;
this only reads text). pdfminer.six (MIT) does the reading; it cannot be
installed in SENAITE's Python 2.7 image (its last Python 2 release needs a C
build), so it runs here. Reachable only from SENAITE on the internal `render`
network; no port is published.

Limits: a 150 MB request; 120 s per scan (the scan runs in a child process,
killed at the limit). Errors answer JSON {"error": "..."} with 400 (the
request) or 500 (the scan).
"""
import io
import json
import multiprocessing
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata

PORT = int(os.environ.get("PORT", "3001"))
MAX_BYTES = 150 * 1024 * 1024
TIMEOUT_S = 120


def _pages(data, out):
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTTextContainer
        texts = []
        for page in extract_pages(io.BytesIO(data), laparams=LAParams()):
            texts.append("".join(e.get_text() for e in page if isinstance(e, LTTextContainer)))
        out.put({"pages": texts})
    except Exception as exc:                                # noqa: BLE001
        out.put({"error": "the PDF could not be read: %s" % exc})


def scan(data):
    out = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_pages, args=(data, out))
    proc.start()
    try:
        result = out.get(timeout=TIMEOUT_S)
    except Exception:                                       # noqa: BLE001
        result = {"error": "the scan took longer than %d s" % TIMEOUT_S, "status": 500}
    proc.join(1)
    if proc.is_alive():
        proc.kill()
    return result


class Handler(BaseHTTPRequestHandler):
    def _answer(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._answer(200, {"ok": True, "pdfminer": metadata.version("pdfminer.six")})
        return self._answer(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/text":
            return self._answer(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0:
            return self._answer(400, {"error": "no PDF"})
        if size > MAX_BYTES:
            return self._answer(400, {"error": "request larger than 150 MB"})
        data = self.rfile.read(size)
        if not data.startswith(b"%PDF"):
            return self._answer(400, {"error": "not a PDF"})
        result = scan(data)
        if "error" in result:
            return self._answer(result.pop("status", 400), {"error": result["error"]})
        return self._answer(200, result)

    def log_message(self, fmt, *args):                      # one line per request
        print("%s %s" % (self.command, self.path), flush=True)


if __name__ == "__main__":
    print("pfas-scan listening on %d" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
