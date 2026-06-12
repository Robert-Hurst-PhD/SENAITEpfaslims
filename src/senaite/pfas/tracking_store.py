# -*- coding: utf-8 -*-
"""
PFAS Client Tracking Store — ZODB-backed mapping of tracking numbers to AR UIDs.

Python 2.7 compatible.

Storage layout
--------------
  IAnnotations(portal)[TRACKING_KEY]        -> PersistentMapping {tracking_number: ar_uid}
  IAnnotations(portal)[TRACKING_BY_UID_KEY] -> PersistentMapping {ar_uid: tracking_number}

Tracking number format: PF-YYMMDD-XXXX
  PF     = PFAS lab prefix (fixed)
  YYMMDD = date received (2-digit year, zero-padded month/day)
  XXXX   = 4-char uppercase alphanumeric suffix (A-Z, 0-9), ~1.68M combinations per day
  e.g.   PF-260611-A3K9

Idempotency
-----------
get_or_assign_tracking() checks the reverse index first — if the AR already has a
tracking number (e.g. from a retract/re-receive), it returns the existing one rather
than minting a new number that would orphan any QR slip already given to the client.
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import logging
import random
import string

from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger('senaite.pfas.tracking_store')

TRACKING_KEY     = u'senaite.pfas.tracking'
TRACKING_BY_UID  = u'senaite.pfas.tracking.by_uid'

_CHARS = string.ascii_uppercase + string.digits  # 36 chars  →  36^4 = 1,679,616 combos/day
_SUFFIX_LEN = 4


def _get_store(portal):
    """Return (fwd_map, rev_map) PersistentMappings, creating them if absent."""
    ann = IAnnotations(portal)
    if TRACKING_KEY not in ann:
        ann[TRACKING_KEY] = PersistentMapping()
    if TRACKING_BY_UID not in ann:
        ann[TRACKING_BY_UID] = PersistentMapping()
    return ann[TRACKING_KEY], ann[TRACKING_BY_UID]


def generate_tracking_number():
    """Mint a candidate PF-YYMMDD-XXXX number (not yet checked for collisions)."""
    today = datetime.date.today()
    date_str = today.strftime('%y%m%d')
    rng = random.SystemRandom()
    suffix = ''.join(rng.choice(_CHARS) for _ in range(_SUFFIX_LEN))
    return 'PF-{0}-{1}'.format(date_str, suffix)


def assign_tracking_number(portal, tracking_number, ar_uid):
    """Store tracking_number <-> ar_uid in both indexes (overwrites old assignment)."""
    fwd, rev = _get_store(portal)
    fwd[tracking_number] = ar_uid
    rev[ar_uid] = tracking_number


def get_ar_uid_by_tracking(portal, tracking_number):
    """Return AR UID for tracking_number, or None."""
    fwd, _rev = _get_store(portal)
    return fwd.get(tracking_number)


def get_tracking_by_ar_uid(portal, ar_uid):
    """Return tracking number for ar_uid, or None if not yet assigned."""
    _fwd, rev = _get_store(portal)
    return rev.get(ar_uid)


def get_or_assign_tracking(portal, ar):
    """Idempotent: return existing tracking number for *ar*, or mint and store one.

    Retries up to 5 times on key collision (extremely unlikely, handled defensively).
    Returns None only if all retries collide.
    """
    ar_uid = ar.UID()
    existing = get_tracking_by_ar_uid(portal, ar_uid)
    if existing:
        return existing

    fwd, rev = _get_store(portal)
    for _attempt in range(5):
        candidate = generate_tracking_number()
        if candidate not in fwd:
            fwd[candidate] = ar_uid
            rev[ar_uid] = candidate
            logger.info('Assigned tracking number %s to AR %s', candidate, ar_uid)
            return candidate

    logger.error('Failed to assign tracking number to AR %s after 5 attempts', ar_uid)
    return None
