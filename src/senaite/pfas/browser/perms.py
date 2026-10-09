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
# definitions, QC criteria). Matches: only Manager / QAO /
# Director / Owner may edit configuration tables.
ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))

# Backwards-compatible alias — logbooks.py used this private name.
_ALLOWED_ROLES = ALLOWED_ROLES


def require_manager(context, request=None):
    """True if the current user holds a management role in this context.

    Never raises: an unauthenticated or broken security context is treated
    as "not a manager" (deny by default).

    Resolved at the PORTAL, not at `context`. The views calling
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
# a LabManager edits lab thresholds, not credentials.
SITE_ADMIN_ROLES = frozenset(("Manager", "Owner"))

# The two tiers an action can be gated at. Anything not named in a view's
# gate table is OPEN — deliberately, because the bench logging actions must stay
# performable by any lab user and by a future service account.
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
    through a reagent they added passed both tiers -- the sensor key included.
    Every store these gates protect is portal-scoped, so the
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


# Narrower sets some older views were written against. Kept as they were --
# moving them onto the portal changed WHERE roles are resolved, not WHO passes.
# Neither contains Owner.
MANAGER_ROLES = frozenset(("Manager", "LabManager"))
ANALYST_ROLES = frozenset(("Analyst", "Verifier"))


def has_role_at_portal(context, roles):
    """Public form of the portal-anchored check, for views with their own set."""
    return _has_any_role(context, frozenset(roles))


def require_site_admin(context, request=None):
    """True if the current user may change structural settings. Never raises."""
    return _has_any_role(context, SITE_ADMIN_ROLES)


def _is_anonymous():
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        return user is None or user.getUserName() == "Anonymous User"
    except Exception:                                       # noqa: BLE001
        return False


def refuse(request, body="Forbidden"):
    """Refuse a request. A visitor who is not signed in -- a session that
    timed out, then a click or a Save -- is sent to the login page and back
    here afterwards (Zope's Unauthorized challenge); a signed-in user without
    the right gets 403 and `body`."""
    if _is_anonymous():
        from zExceptions import Unauthorized
        raise Unauthorized("Please sign in.")
    request.response.setStatus(403)
    return body


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
    return refuse(request)


class GateMixin(object):
    """What a gated view's TEMPLATE asks, so a control the user cannot use is
    not drawn. The server-side gate stays authoritative: hiding
    a button is presentation, and deny_gated_action still refuses the POST.
    """

    def can_configure(self):
        return require_manager(self.context, self.request)

    def can_site_admin(self):
        return require_site_admin(self.context, self.request)



# ── Clients see the client pages only ──────────────────
# Most PFAS pages are registered with zope2.View, which a client's user holds
# too: a signed-in client could open the Bench (every client's batches), QC
# Management and the Reagent Inventory by URL -- the sidebar hid them, nothing
# refused them. Anyone signed in without a lab role at the portal (SENAITE's
# own roles) is refused every @@pfas-* page but these.
STAFF_ROLES = frozenset(("Manager", "LabManager", "LabClerk", "Analyst", "Verifier",
                         "Sampler", "SamplingCoordinator", "Preserver", "Publisher",
                         "RegulatoryInspector", "Owner"))
CLIENT_VIEWS = frozenset((
    "pfas-track", "pfas-home", "pfas-sample-status", "pfas-ar-tracker", "pfas-receipt",
    "pfas-help",
    # the chain of custody: a client enters their own samples
    "pfas-coc", "pfas-coc-print",
    # page chrome every page draws, and the signed-out / machine entry points
    "pfas-macros", "pfas-topbar", "pfas-sidebar", "pfas-sidebar-pins",
    "pfas-logbook-macros", "pfas-config-form-macros", "pfas-badge-signin",
    "pfas-sensor-ingest",
))


# What a visitor who is NOT signed in may open: the pages registered
# zope2.Public (the client tracker, badge sign-in, the sensor ingest with its
# own API key, and the macro views pages are drawn with). Anonymous holds View
# on the portal, so every other @@pfas-* page -- registered zope2.View -- was
# reachable signed out, writes included, and plone.protect does not check
# anonymous requests (F1 / F4).
ANON_VIEWS = frozenset((
    "pfas-track", "pfas-badge-signin", "pfas-sensor-ingest",
    "pfas-macros", "pfas-topbar", "pfas-logbook-macros", "pfas-config-form-macros",
    "pfas-blank-history-macros",
))


# Configuration pages core protects with "senaite.core: Manage Bika" alone,
# which core grants the LabClerk too: the Bench Chemist could rewrite every
# method's QC types, the certificate qualifiers and the CoA register.
# Configuration is the manager's.
MANAGER_VIEWS = frozenset((
    "pfas-qc-type-grid", "pfas-print-settings", "pfas-method-wizard",
    "pfas-controlled-publications", "pfas-lab-settings",
))


def is_json_api(request):
    """senaite.jsonapi (@@API/senaite/v1/...): the catalog returns every
    analysis's result whatever its state, so a client read unreviewed
    results there, and a signed-out caller listed reagents (H3 / F4). The worker signs in as staff."""
    import re
    path = request.get("PATH_INFO") or ""
    # senaite.jsonapi (API/senaite/v1) and core's older API (@@API/read,
    # update...) alike
    return re.search(r"/(@@)?API/", path) is not None


def _view_name(published):
    view = getattr(published, "__self__", published)      # a view's method
    return getattr(view, "__name__", "") or ""


def is_staff(context):
    return _has_any_role(context, STAFF_ROLES)


def _host(url):
    """The host name of an Origin / Referer / server URL, lower case, no
    port (nginx forwards Host without one; the tunnel and the direct port
    differ only by it)."""
    try:
        from urlparse import urlsplit
    except ImportError:                                     # Python 3 (tests)
        from urllib.parse import urlsplit
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def cross_site_post(request):
    """True when a POST comes from another site's page. Nineteen PFAS
    handlers switch plone.protect off, and SQLite and file writes are never
    covered by it, so a page elsewhere could make a signed-in Manager's
    browser approve a release. Browsers send
    Origin with every cross-site POST ("null" from a sandboxed or privacy-
    stripped one); Referer is the fallback. A request carrying neither is not
    from a browser page (a script or device) and is left to the view."""
    if (request.get("REQUEST_METHOD") or "").upper() != "POST":
        return False
    origin = request.getHeader("Origin") if hasattr(request, "getHeader") else None
    source = origin if origin else (
        request.getHeader("Referer") if hasattr(request, "getHeader") else None)
    if not source:
        return False
    # "null" (and anything unparsable) has no host, so it is never ours
    own = set(h for h in (_host(request.get("SERVER_URL")),
                          _host("//" + (request.get("HTTP_HOST") or "")),
                          _host("//" + (request.get("HTTP_X_FORWARDED_HOST") or "")))
              if h)
    return _host(source) not in own


def keep_clients_out(event):
    """IPubAfterTraversal: a visitor who is not signed in reaches only the
    public PFAS pages (ANON_VIEWS) -- any other, read or write, sends them to
    sign in; a signed-in user who holds no lab role (a client) is refused
    every PFAS staff page and the JSON API; the configuration pages core
    leaves to LabClerk are the manager's (MANAGER_VIEWS); and no PFAS page
    or JSON API call accepts a POST from another site."""
    request = event.request
    if is_json_api(request):
        if cross_site_post(request):
            from zExceptions import Forbidden
            raise Forbidden("This request was sent from another site.")
        if _is_anonymous():
            from zExceptions import Unauthorized
            raise Unauthorized("Please sign in.")
        if not is_staff(_portal()):
            from zExceptions import Forbidden
            raise Forbidden("The data interface is for laboratory staff.")
        return
    name = _view_name(request.get("PUBLISHED"))
    # a page, not a static resource: ++resource++senaite.pfas/pfas-tokens.css
    # publishes under its file name, and refusing it left the sign-in page,
    # the tracker and every client page without their stylesheet
    if not name.startswith("pfas-") or "." in name:
        return
    if cross_site_post(request):
        from zExceptions import Forbidden
        raise Forbidden("This form was sent from another site.")
    if _is_anonymous():
        if name in ANON_VIEWS:
            return
        from zExceptions import Unauthorized
        raise Unauthorized("Please sign in.")
    if name in CLIENT_VIEWS:
        return
    portal = _portal()
    if portal is not None and is_staff(portal):
        if name in MANAGER_VIEWS and not require_manager(portal):
            from zExceptions import Forbidden
            raise Forbidden("This configuration page is for lab managers.")
        return
    from zExceptions import Unauthorized
    raise Unauthorized("This page is for laboratory staff.")


def _portal():
    try:
        from bika.lims import api
        return api.get_portal()
    except Exception:                                       # noqa: BLE001
        return None
