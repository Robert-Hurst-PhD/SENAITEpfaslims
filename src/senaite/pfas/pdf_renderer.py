# -*- coding: utf-8 -*-
"""Client for the document renderer container.

pfas-render runs pdfme's generator (tools/pdfme/server.mjs) on the internal
`render` network; SENAITE asks it for the PDF of a designed document:

    render(template, inputs) -> PDF bytes      (raises RenderError)
    render_documents([(template, input), ...]) -> one PDF, in order: each
        document from its own compiled template (document_templates.
        compile_document), so its every-page fields carry its own values
    health()                 -> {"ok": True, "pdfme": "6.2.2"} or None

A caller printing a CONTROLLED document from an issued template must not fall
back to another layout when this raises: it refuses, and says why.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import os

from six.moves.urllib.error import HTTPError, URLError
from six.moves.urllib.request import Request, urlopen

RENDER_URL = os.environ.get("PFAS_RENDER_URL", "http://pfas-render:3000")
TIMEOUT = 90          # the renderer gives up after 60 s


class RenderError(Exception):
    """The renderer could not produce the PDF; the message says why."""


def _post(url, payload, timeout):
    body = json.dumps(payload)
    if not isinstance(body, bytes):
        body = body.encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    return urlopen(req, timeout=timeout)


def render(template, inputs, timeout=TIMEOUT, url=None):
    return _render({"template": template, "inputs": inputs}, timeout, url)


def _render(payload, timeout, url):
    try:
        resp = _post((url or RENDER_URL) + "/render", payload, timeout)
        data = resp.read()
    except HTTPError as exc:
        try:
            why = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:                                   # noqa: BLE001
            why = None
        raise RenderError(u"The document renderer refused it: %s" % (why or exc.code))
    except (URLError, IOError, OSError) as exc:
        raise RenderError(u"The document renderer is not reachable (%s)." % (
            getattr(exc, "reason", None) or exc))
    if not data.startswith(b"%PDF"):
        raise RenderError(u"The document renderer did not return a PDF.")
    return data


def render_documents(documents, timeout=TIMEOUT, url=None):
    return _render({"documents": [{"template": t, "inputs": [i]} for t, i in documents]},
                   timeout, url)


def health(timeout=5, url=None):
    try:
        resp = urlopen((url or RENDER_URL) + "/health", timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:                                       # noqa: BLE001
        return None
