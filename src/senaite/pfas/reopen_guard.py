# -*- coding: utf-8 -*-
"""Only Verify's Send back reopens a submitted worksheet.

Core reopens a worksheet that waits for verification (or a verified one)
through its own "retract", and through an analysis's "retract", whose
retest is added to the worksheet and rolls it back to open. Both happen
here only on purpose: inside Send back, and inside an identity correction
retracting results already filed. Those two run their transitions inside
`allowing(request)`, which marks the request; the guard adapter
(browser/guards.ReopenGuard) refuses the transitions on any request without
the mark. Core offers a transition only when its guard passes, so the
plain Retract is hidden from every listing and menu, and a URL firing it is
refused the same way.

An analysis's retract on an open worksheet is not refused: Integration Review and the
identity correction retract there, and the worksheet is already open.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import contextlib

MARK = "senaite.pfas.reopen_allowed"
# the worksheet states only Send back leaves for open
CLOSED_STATES = ("to_be_verified", "verified")
RETRACT = "retract"


def allowed(kind, transition, ws_state, is_marked):
    """Whether `transition` may run on a "worksheet" or an "analysis" (on a
    worksheet in `ws_state`, None on none)."""
    if transition != RETRACT or is_marked:
        return True
    if kind == "worksheet":
        return False
    if kind == "analysis":
        return ws_state not in CLOSED_STATES
    return True


def marked(request):
    try:
        return bool(request is not None and request.get(MARK))
    except Exception:                                       # noqa: BLE001
        return False


@contextlib.contextmanager
def allowing(request):
    """The block in which a reopen is intended; the mark is cleared after
    it, whatever happens in it."""
    request.set(MARK, True)
    try:
        yield
    finally:
        request.set(MARK, False)
