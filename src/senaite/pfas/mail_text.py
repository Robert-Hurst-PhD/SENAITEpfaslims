# -*- coding: utf-8 -*-
"""One plain-text e-mail as the bytes MailHost.send takes.

The subject carries the laboratory's name, which may hold non-ASCII
letters: a header holds only ASCII, so such a subject is encoded (RFC 2047)
and the body is declared UTF-8. Standard library only. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from email.charset import QP, Charset
from email.header import Header
from email.message import Message


def _ascii(text):
    try:
        text.encode("ascii")
        return True
    except UnicodeError:
        return False


def message(sender, to, subject, body):
    """The message as bytes: From, To and Subject headers, a UTF-8 body."""
    charset = Charset("utf-8")
    charset.body_encoding = QP          # the body stays readable in the raw mail
    text = body if not isinstance(body, bytes) else body.decode("utf-8")
    if str is bytes:                    # Python 2: the payload is encoded bytes
        text = text.encode("utf-8")
    msg = Message()
    msg.set_payload(text, charset)
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject if _ascii(subject) else Header(subject, "utf-8").encode()
    raw = msg.as_string()
    return raw if isinstance(raw, bytes) else raw.encode("ascii")
