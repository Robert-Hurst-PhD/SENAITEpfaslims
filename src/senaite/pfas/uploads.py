# -*- coding: utf-8 -*-
"""Files people upload (certificates of analysis, controlled documents):
the content type is decided by the file's extension, never by the header
the browser sends, so a file is served only as what its name says it is."""
from __future__ import absolute_import, unicode_literals

import os

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def content_type_for(filename):
    """The content type an uploaded file is stored and served as, from its
    extension; None when the extension is not one the lab accepts."""
    if not filename:
        return None
    return CONTENT_TYPES.get(os.path.splitext(os.path.basename(filename))[1].lower())
