# -*- coding: utf-8 -*-
"""
PFAS Client Tracking Store — ZODB-backed mapping of tracking numbers to AR UIDs.

Python 2.7 compatible.

Storage layout
--------------
  IAnnotations(portal)[TRACKING_KEY]        -> PersistentMapping {tracking_number: ar_uid}
  IAnnotations(portal)[TRACKING_BY_UID_KEY] -> PersistentMapping {ar_uid: tracking_number}

Tracking number format: PF-YYMMDD-XXXXXXXX
  PF       = PFAS lab prefix (fixed)
  YYMMDD   = date received (2-digit year, zero-padded month/day)
  XXXXXXXX = 8-char uppercase alphanumeric suffix (A-Z, 0-9), 36^8 = 2.8e12 per
             day, so a day's numbers cannot be found by trying them (numbers
             issued with the earlier 4-character suffix still work)
  e.g.     PF-260611-A3K9Q7ZD
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import random
import string

from senaite.pfas import lab_time
from senaite.pfas.annotation_store import mapping

logger = logging.getLogger('senaite.pfas.tracking_store')

TRACKING_KEY     = u'senaite.pfas.tracking'
TRACKING_BY_UID  = u'senaite.pfas.tracking.by_uid'

_CHARS = string.ascii_uppercase + string.digits
_SUFFIX_LEN = 8


def _get_store(portal, create=False):
    """(fwd_map, rev_map); a lookup (the anonymous tracker) creates neither."""
    return mapping(portal, TRACKING_KEY, create), mapping(portal, TRACKING_BY_UID, create)


def generate_tracking_number():
    """Mint a candidate PF-YYMMDD-XXXXXXXX number (not yet checked for collisions)."""
    today = lab_time.today()
    date_str = today.strftime('%y%m%d')
    rng = random.SystemRandom()
    suffix = ''.join(rng.choice(_CHARS) for _ in range(_SUFFIX_LEN))
    return 'PF-{0}-{1}'.format(date_str, suffix)


def get_ar_uid_by_tracking(portal, tracking_number):
    """Return AR UID for tracking_number, or None."""
    fwd, _rev = _get_store(portal)
    return fwd.get(tracking_number)


def get_tracking_by_ar_uid(portal, ar_uid):
    """Return tracking number for ar_uid, or None if not yet assigned."""
    _fwd, rev = _get_store(portal)
    return rev.get(ar_uid)


def tracking_for(portal, ar):
    """(tracking number, the sample that holds it) for `ar`, or (None, None).

    A sample's own number; for a retest, the number of the sample it
    re-analyses. Core creates a retest already received (no 'receive'
    transition), so it is never given a number of its own: the client keeps
    the original's slip, and the tracker follows that slip from the
    invalidated original to its retest."""
    seen = set()
    while ar is not None and ar.UID() not in seen:
        seen.add(ar.UID())
        number = get_tracking_by_ar_uid(portal, ar.UID())
        if number:
            return number, ar
        ar = ar.getInvalidated() if hasattr(ar, 'getInvalidated') else None
    return None, None


def get_or_assign_tracking(portal, ar):
    """Idempotent: the existing tracking number for *ar* (the reverse index,
    e.g. after a retract / re-receive), else a new one minted and stored. A
    second number would orphan the QR slip the client already holds.

    Retries up to 5 times on key collision (extremely unlikely, handled defensively).
    Returns None only if all retries collide.
    """
    ar_uid = ar.UID()
    existing = get_tracking_by_ar_uid(portal, ar_uid)
    if existing:
        return existing

    fwd, rev = _get_store(portal, create=True)
    for _attempt in range(5):
        candidate = generate_tracking_number()
        if candidate not in fwd:
            fwd[candidate] = ar_uid
            rev[ar_uid] = candidate
            logger.info('Assigned tracking number %s to AR %s', candidate, ar_uid)
            return candidate

    logger.error('Failed to assign tracking number to AR %s after 5 attempts', ar_uid)
    return None
