# -*- coding: utf-8 -*-
"""Reading and writing an object's annotations, the same way everywhere.

    mapping(obj, key, create=True)   the PersistentMapping at `key`; a read
                                     passes create=False and gets {} when
                                     there is none, so a page view writes
                                     nothing to the ZODB
    read_json(obj, key, default)     the JSON value at `key`, or a copy of
                                     `default` when there is none or it does
                                     not parse
"""
from __future__ import absolute_import, unicode_literals

import copy
import json


def mapping(obj, key, create=True):
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(obj)
    found = ann.get(key)
    if found is None:
        if not create:
            return {}
        from persistent.mapping import PersistentMapping
        found = ann[key] = PersistentMapping()
    return found


def read_json(obj, key, default):
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(obj).get(key)
        return json.loads(raw) if raw else copy.deepcopy(default)
    except (TypeError, ValueError):
        return copy.deepcopy(default)
