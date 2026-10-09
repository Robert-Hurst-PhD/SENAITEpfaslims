# -*- coding: utf-8 -*-
"""Sign-in avatars: the pixel-art picture on a person's sign-in tile.

The pictures are made in-house (tools/make_login_art.py) and served from
++resource++senaite.pfas/login/avatars/<id>.png. A person chooses theirs on
Profile & signature; until then one is picked from their user id, so it is
the same on every terminal.

Storage: one annotation on the portal, {user id: avatar id} (the sidebar_pins
pattern). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import hashlib

from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

KEY = "senaite.pfas.avatars"

# (id, label): tools/make_login_art.py draws one PNG per id
AVATARS = [
    ("flask", "Flask"), ("beaker", "Beaker"), ("test-tube", "Test tube"),
    ("pipette", "Pipette"), ("microscope", "Microscope"), ("molecule", "Molecule"),
    ("atom", "Atom"), ("droplet", "Droplet"), ("balance", "Balance"),
    ("goggles", "Goggles"), ("column", "LC column"), ("vial", "Vial"),
    ("petri-dish", "Petri dish"), ("thermometer", "Thermometer"),
    ("chromatogram", "Chromatogram"), ("benzene", "Benzene ring"),
]
IDS = [a[0] for a in AVATARS]


def default_for(userid):
    """The picture a person has before choosing one: fixed by their user id."""
    digest = hashlib.sha256(("%s" % (userid or "")).encode("utf-8")).hexdigest()
    return IDS[int(digest[:8], 16) % len(IDS)]


def get(portal, userid):
    chosen = (IAnnotations(portal).get(KEY) or {}).get(userid)
    return chosen if chosen in IDS else default_for(userid)


def choose(portal, userid, avatar_id):
    if avatar_id not in IDS:
        raise ValueError("unknown picture %s" % avatar_id)
    ann = IAnnotations(portal)
    store = ann.get(KEY)
    if store is None:
        store = ann[KEY] = PersistentMapping()
    store[userid] = avatar_id


def url(portal_url, avatar_id):
    return "%s/++resource++senaite.pfas/login/avatars/%s.png" % (portal_url, avatar_id)
