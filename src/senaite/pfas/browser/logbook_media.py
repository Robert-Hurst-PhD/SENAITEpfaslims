# -*- coding: utf-8 -*-
"""
@@pfas-logbook-media — storage and serving for guided-step images (GIF/photo).

Follows the add-on's established binary convention (see sop_documents.py,
reagents.py): the BYTES live on the filesystem under /data, and only a token
string is stored in ZODB (inside the logbook definition's steps_json). There
is no NamedBlobFile/NamedBlobImage usage anywhere in this add-on, and a Data.fs
full of GIFs would wreck pack/backup times.

Filenames are IMMUTABLE tokens (uuid4 hex + extension) and are never
overwritten. That matters for controlled documents: `_handle_new_revision`
copies a definition verbatim, so a draft shares its parent's tokens, and
replacing a step image mints a NEW token rather than mutating the file an
archived revision still points at. PreparedStandard pins
(logbook_slug, logbook_revision), so an archived revision's imagery must stay
byte-identical forever.

GET  ?f=<token>        → serve inline (so it renders in an <img>)
POST action=upload     → multipart, manager-only, returns JSON {ok, token, url}

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import re
import uuid

from Products.Five.browser import BrowserView
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import require_manager

logger = logging.getLogger("senaite.pfas.browser.logbook_media")

MEDIA_DIR = os.environ.get("PFAS_LOGBOOK_MEDIA_DIR", "/data/logbook_media")
MEDIA_MAX_BYTES = 8 * 1024 * 1024

# extension -> content type. The served Content-Type is derived from the
# token's extension, NEVER from anything the uploader supplied.
MEDIA_EXT_CT = {
    ".gif":  "image/gif",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Leading bytes each format must start with. An extension check alone is not
# enough: a ".gif" whose body is HTML, served inline, is a stored-XSS vector.
_MAGIC = {
    ".gif":  (b"GIF87a", b"GIF89a"),
    ".png":  (b"\x89PNG\r\n\x1a\n",),
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}

# A token is exactly 32 hex chars + a known extension. Anything else is
# rejected BEFORE a filesystem path is constructed, so traversal is impossible
# by construction rather than by escaping.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}\.(gif|png|jpg|jpeg)$")


def _ext_of(token):
    return os.path.splitext(token)[1].lower()


def save_media(upload):
    """Persist an uploaded image. Returns (token, error_message).

    On success error_message is None; on failure token is None.
    """
    if upload is None or not getattr(upload, "filename", ""):
        return None, "No file received."

    raw_name = os.path.basename(getattr(upload, "filename", "") or "")
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in MEDIA_EXT_CT:
        return None, "Only GIF, PNG and JPEG images are accepted."

    try:
        data = upload.read()
    except Exception as exc:
        logger.warning("save_media: read failed: %s", exc)
        return None, "Could not read the uploaded file."

    if not data:
        return None, "The uploaded file is empty."
    if len(data) > MEDIA_MAX_BYTES:
        return None, "Image is larger than {0} MB.".format(
            MEDIA_MAX_BYTES // (1024 * 1024))

    if not any(data.startswith(sig) for sig in _MAGIC[ext]):
        return None, "That file is not a real {0} image.".format(ext.lstrip("."))

    if not os.path.isdir(MEDIA_DIR):
        try:
            os.makedirs(MEDIA_DIR)
        except OSError as exc:
            logger.error("save_media: cannot create %s: %s", MEDIA_DIR, exc)
            return None, "Media directory unavailable."

    token = "{0}{1}".format(uuid.uuid4().hex, ext)
    dest = os.path.join(MEDIA_DIR, token)
    tmp = dest + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.rename(tmp, dest)          # atomic: never a half-written image
    except Exception as exc:
        logger.error("save_media: write failed: %s", exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return None, "Could not store the image."

    logger.info("logbook step media stored: %s (%d bytes)", token, len(data))
    return token, None


class PFASLogbookMediaView(BrowserView):
    """Serve (GET) and accept (POST) guided-step images."""

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_upload()
        return self._serve()

    # ── read ──────────────────────────────────────────────────────────────
    def _serve(self):
        token = (self.request.form.get("f") or "").strip()
        # Reject before building a path — no traversal surface at all.
        if not _TOKEN_RE.match(token):
            self.request.response.setStatus(404)
            return "Not found"

        path = os.path.realpath(os.path.join(MEDIA_DIR, token))
        root = os.path.realpath(MEDIA_DIR)
        if not path.startswith(root):
            # Unreachable given the regex; kept as defence in depth.
            self.request.response.setStatus(403)
            return "Forbidden"
        if not os.path.isfile(path):
            self.request.response.setStatus(404)
            return "Not found"

        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception as exc:
            logger.warning("media read failed for %s: %s", token, exc)
            self.request.response.setStatus(404)
            return "Not found"

        resp = self.request.response
        resp.setHeader("Content-Type", MEDIA_EXT_CT[_ext_of(token)])
        resp.setHeader("Content-Length", str(len(data)))
        resp.setHeader("Content-Disposition",
                       'inline; filename="{0}"'.format(token))
        # Never let a browser sniff this into something executable.
        resp.setHeader("X-Content-Type-Options", "nosniff")
        # Tokens are immutable, so this can cache hard.
        resp.setHeader("Cache-Control", "public, max-age=31536000")
        return data

    # ── write ─────────────────────────────────────────────────────────────
    def _json(self, payload, status=200):
        self.request.response.setStatus(status)
        self.request.response.setHeader("Content-Type", "application/json")
        return json.dumps(payload)

    def _handle_upload(self):
        # Uploading step imagery is editing lab configuration.
        if not require_manager(self.context, self.request):
            return self._json({"ok": False, "error": "Forbidden"}, status=403)
        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass

        upload = self.request.form.get("media")
        token, error = save_media(upload)
        if error:
            return self._json({"ok": False, "error": error}, status=400)
        return self._json({
            "ok": True,
            "token": token,
            "url": "{0}?f={1}".format(self.context.absolute_url()
                                      + "/@@pfas-logbook-media", token),
        })
