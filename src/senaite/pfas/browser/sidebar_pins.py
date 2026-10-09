# -*- coding: utf-8 -*-
"""Per-user sidebar pins: pages a person pins appear under Dashboard.

Requested 2026-09-30 ("pin things underneath the dashboard, similar to
Windows Explorer"), stored on the server so pins follow the person to any lab
computer.

Storage: one annotation on the portal, {user id: [path, ...]}, where a path is
a sidebar link relative to the portal ("@@pfas-reagents", "samples"). Only the
path is stored. The sidebar renders a pin by copying the user's OWN sidebar
link for that path, so its label and icon come from the one sidebar
definition, and a page the user can no longer reach simply does not appear.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import re

from AccessControl import getSecurityManager
from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from plone.protect import CheckAuthenticator
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations
from zExceptions import Forbidden

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse

PINS_KEY = "senaite.pfas.sidebar_pins"
MAX_PINS = 20
# A portal-relative sidebar path: view names, folder ids, query strings.
# No scheme, no leading slash, no "..", nothing that is not a plain path.
_PATH_RE = re.compile(r"^[A-Za-z0-9@_\-./?=&]{1,200}$")


def _portal(context):
    return getToolByName(context, "portal_url").getPortalObject()


def _user_id():
    user = getSecurityManager().getUser()
    uid = user.getId() if user is not None else None
    if not uid or uid == "Anonymous User":
        return None
    return uid


def valid_path(path):
    return bool(path and _PATH_RE.match(path) and ".." not in path
                and not path.startswith("/") and "//" not in path)


def get_pins(context, user_id=None):
    """The pinned paths of a user (default: the current user), in pin order."""
    uid = user_id or _user_id()
    if not uid:
        return []
    store = IAnnotations(_portal(context)).get(PINS_KEY) or {}
    return list(store.get(uid, []))


def set_pin(context, path, pinned, user_id=None):
    """Pin or unpin one path for a user; returns the new list."""
    uid = user_id or _user_id()
    if not uid:
        raise Forbidden("Log in to pin pages.")
    if not valid_path(path):
        raise ValueError("Not a sidebar path: {0!r}".format(path))
    ann = IAnnotations(_portal(context))
    store = ann.get(PINS_KEY)
    if store is None:
        store = ann[PINS_KEY] = PersistentMapping()
    pins = store.get(uid)
    if pins is None:
        pins = store[uid] = PersistentList()
    if pinned and path not in pins:
        if len(pins) >= MAX_PINS:
            raise ValueError("At most {0} pins.".format(MAX_PINS))
        pins.append(path)
    elif not pinned and path in pins:
        pins.remove(path)
    return list(pins)


class PFASSidebarPinsView(BrowserView):
    """POST @@pfas-sidebar-pins  path=<sidebar path>  pinned=1|0
    (+ _authenticator). Answers with the user's pins as JSON."""

    def __call__(self):
        flatten_form(self.request)
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.get("REQUEST_METHOD", "GET") != "POST":
            return json.dumps({"pins": get_pins(self.context)})
        try:
            CheckAuthenticator(self.request)
            pins = set_pin(self.context, self.request.form.get("path", ""),
                           self.request.form.get("pinned") in ("1", "true", "on"))
        except Forbidden as exc:
            return refuse(self.request, json.dumps({"error": str(exc) or "Forbidden"}))
        except ValueError as exc:
            resp.setStatus(400)
            return json.dumps({"error": str(exc)})
        return json.dumps({"pins": pins})
