# -*- coding: utf-8 -*-
"""
Shared role gate for PFAS management views.

Extracted from browser/logbooks.py so that sibling management views
(prep logbook definitions, logbook step media) can enforce the SAME rule
without importing each other — a module-level back-import between
logbooks.py and prep_logbooks.py would be a cycle waiting to happen.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

# Roles permitted to edit lab configuration (method profiles, logbook
# definitions, QC criteria). Matches CLAUDE.md §4: only Manager / QAO /
# Director / Owner may edit configuration tables.
ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))

# Backwards-compatible alias — logbooks.py used this private name.
_ALLOWED_ROLES = ALLOWED_ROLES


def require_manager(context, request=None):
    """True if the current user holds a management role in this context.

    Never raises: an unauthenticated or broken security context is treated
    as "not a manager" (deny by default).

    Resolved at the PORTAL, not at `context` (GAPS §46.6). The views calling
    this are registered `for="*"`, and Plone makes the creator of any object
    its local `Owner`, so resolved at the context a bench chemist reached the
    QC-criteria editor through any reagent they had added.
    """
    return _has_any_role(context, ALLOWED_ROLES)


# Backwards-compatible alias — logbooks.py used this private name.
_require_manager = require_manager


# Roles permitted to change STRUCTURAL settings — secrets whose holder can act
# as the system, such as the sensor API key that authenticates the
# unauthenticated ingest endpoint. Deliberately narrower than ALLOWED_ROLES:
# a LabManager edits lab thresholds, not credentials (GAPS §46).
SITE_ADMIN_ROLES = frozenset(("Manager", "Owner"))

# The two tiers an action can be gated at. Anything not named in a view's
# gate table is OPEN — deliberately, because the bench logging actions must stay
# performable by any lab user and by a future service account (CLAUDE.md §4).
TIER_CONFIG = "config"
TIER_SITE_ADMIN = "site_admin"

_TIER_ROLES = {
    TIER_CONFIG: ALLOWED_ROLES,
    TIER_SITE_ADMIN: SITE_ADMIN_ROLES,
}


def _has_any_role(context, roles):
    """Whether the user holds one of `roles` AT THE PORTAL.

    Never at `context`. The gated views are registered `for="*"`, so they can be
    reached through any object, and Zope grants the `Owner` LOCAL role to
    whoever creates an object. Resolved at the context, a bench chemist posting
    through a reagent they added passed both tiers -- the sensor key included
    (GAPS §46.5). Every store these gates protect is portal-scoped, so the
    portal is the only place the question means anything. Any failure to
    resolve the portal denies.
    """
    try:
        from AccessControl import getSecurityManager
        portal = context.portal_url.getPortalObject()
        user = getSecurityManager().getUser()
        return bool(roles.intersection(user.getRolesInContext(portal)))
    except Exception:
        return False


def require_site_admin(context, request=None):
    """True if the current user may change structural settings. Never raises."""
    return _has_any_role(context, SITE_ADMIN_ROLES)


def deny_gated_action(context, request, action, gates):
    """Refuse a POST whose action is gated above the current user's roles.

    `gates` maps action name -> TIER_CONFIG / TIER_SITE_ADMIN. Returns the
    response body to return immediately (with the status already set to 403)
    when the user lacks the tier, else None. An action absent from `gates` is
    open. An unknown tier DENIES — a typo in a gate table must fail closed.

    Callers must invoke this BEFORE disabling CSRF protection and before any
    handler runs, so an unauthorised POST never reaches either.
    """
    tier = gates.get(action)
    if tier is None:
        return None
    roles = _TIER_ROLES.get(tier)
    if roles is not None and _has_any_role(context, roles):
        return None
    request.response.setStatus(403)
    return "Forbidden"
