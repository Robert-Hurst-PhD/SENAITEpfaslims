# -*- coding: utf-8 -*-
"""The EDD export's formats. The export tool is
generic; each format is a module here that a profile names in its `format`
(or `base`): its row layout, its seed profile, the forms the settings page
shows for it and its value-list refresh. A profile cloned from another keeps
its format.

    FORMATS                     {format id: module}
    DEFAULT_PROFILE_ID          the profile a new install starts with
    format_of(profile)          the format module a profile uses
    seed_profiles()             {profile id: profile} for a new install

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from . import egad_v6

FORMATS = {egad_v6.PROFILE_ID: egad_v6}
DEFAULT_PROFILE_ID = egad_v6.PROFILE_ID


def format_of(profile):
    """The format module a profile uses (its `format`, else its `base`, else
    the default format)."""
    p = profile or {}
    for key in ("format", "base"):
        mod = FORMATS.get(p.get(key) or "")
        if mod is not None:
            return mod
    return FORMATS[DEFAULT_PROFILE_ID]


def seed_profiles():
    return {DEFAULT_PROFILE_ID: egad_v6.seed_profile()}
