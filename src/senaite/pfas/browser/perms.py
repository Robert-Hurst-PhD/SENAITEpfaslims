# -*- coding: utf-8 -*-
"""
Shared role gate for PFAS management views.

Extracted from browser/logbooks.py so that sibling management views
(logbook step media among them) can enforce the SAME rule without
importing each other: a module-level back-import between two views would
be a cycle waiting to happen.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

# Roles permitted to edit lab configuration (method profiles, logbook
# definitions, QC criteria): only Manager / QAO /
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


# The pipeline worker's own account: a group holding the worker's role and
# the two core roles its JSON pushes need (Analyst: an analysis's result and
# remarks, a worksheet's attachments; Lab Clerk: a client batch's remarks),
# never Manager. The worker's role holds WORKER_PERMISSION, which the
# endpoints only the worker (or a Manager) calls are protected by
# (setuphandlers.setup_worker_role).
WORKER_ROLE = "PFASWorker"
WORKER_GROUP = "PFASWorkers"
WORKER_GROUP_ROLES = (WORKER_ROLE, "Analyst", "LabClerk")
WORKER_PERMISSION = "senaite.pfas: Worker tasks"
WORKER_PERMISSION_ROLES = ("Manager", "Site Administrator", WORKER_ROLE)


def may_run_worker_tasks(context):
    """True when the current user holds WORKER_PERMISSION at the portal (the
    worker's account, a Manager). Never raises."""
    try:
        from AccessControl import getSecurityManager
        portal = context.portal_url.getPortalObject()
        return bool(getSecurityManager().checkPermission(WORKER_PERMISSION, portal))
    except Exception:                                       # noqa: BLE001
        return False


# Narrower role sets for views that name their own.
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


def disable_csrf(request):
    """Switch plone.protect's token check off for this request: PFAS forms
    carry no _authenticator. Call it only after the view's role gate has
    run, so a refused POST is still rolled back."""
    try:
        from plone.protect.interfaces import IDisableCSRFProtection
        from zope.interface import alsoProvides
        alsoProvides(request, IDisableCSRFProtection)
    except ImportError:
        pass


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
# The Regulatory Inspector is the auditor: it passes the client wall to read
# the lab's pages, but holds none of the roles that change anything. A
# signed-in user whose only staff role is the inspector's posts nothing.
READ_ONLY_STAFF_ROLES = frozenset(("RegulatoryInspector",))
WRITE_STAFF_ROLES = STAFF_ROLES - READ_ONLY_STAFF_ROLES
CLIENT_VIEWS = frozenset((
    "pfas-track", "pfas-home", "pfas-ar-tracker", "pfas-receipt",
    "pfas-help",
    # the chain of custody: a client enters their own samples
    "pfas-coc", "pfas-coc-print",
    # page chrome every page draws, and the signed-out / machine entry points
    "pfas-macros", "pfas-topbar", "pfas-sidebar", "pfas-sidebar-pins",
    "pfas-record-macros", "pfas-config-form-macros", "pfas-badge-signin",
    "pfas-sensor-ingest", "pfas-row-menu", "pfas-type-icons", "pfas-icons",
))


# Of those, the page a client writes on: a read-only staff account posts
# nothing there either.
CLIENT_WRITE_VIEWS = frozenset(("pfas-coc",))


# What a visitor who is NOT signed in may open: the pages registered
# zope2.Public (the client tracker, badge sign-in, the sensor ingest with its
# own API key, and the macro views pages are drawn with). Anonymous holds View
# on the portal, so every other @@pfas-* page -- registered zope2.View -- was
# reachable signed out, writes included, and plone.protect does not check
# anonymous requests (F1 / F4).
ANON_VIEWS = frozenset((
    "pfas-track", "pfas-badge-signin", "pfas-sensor-ingest",
    "pfas-macros", "pfas-topbar", "pfas-record-macros", "pfas-config-form-macros",
    "pfas-blank-history-macros", "pfas-row-menu", "pfas-type-icons", "pfas-icons",
))


# Configuration pages core protects with "senaite.core: Manage Bika" alone,
# which core grants the LabClerk too: the Bench Chemist could rewrite every
# method's QC types, the certificate qualifiers and the CoA register.
# Configuration is the manager's.
MANAGER_VIEWS = frozenset((
    "pfas-print-settings", "pfas-qc-qualifiers", "pfas-report-tiers",
    "pfas-method-wizard",
    "pfas-controlled-publications", "pfas-lab-settings", "pfas-backups",
    "pfas-laboratory", "pfas-people", "pfas-time-language", "pfas-system",
    "pfas-signatures",
))


# Of those, what the read-only inspector may open, by GET only: the
# certificate register, to read and download it.
INSPECTOR_READ_VIEWS = frozenset(("pfas-controlled-publications",))

# Who may download a stored certificate's PDF: the roles core's own download
# gives it to (senaite.core: Manage Analysis Requests, held at the portal),
# and the inspector, who reads and takes copies but changes nothing.
CORE_REPORT_ROLES = frozenset(("Manager", "LabManager", "LabClerk", "Analyst", "Publisher"))
CERTIFICATE_READ_ROLES = CORE_REPORT_ROLES | READ_ONLY_STAFF_ROLES


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


# SENAITE's listing fetches a list's rows by a POST to the list's own view
# (<view>/folderitems): reading, which the read-only inspector may do; any
# other subpath of a listing (a transition, a field set) is a write
LISTING_READS = frozenset(("folderitems", "query_folderitems", "get_children"))


# A download a page's own form asks for by POST: reading, which the
# read-only inspector may do. (page, action)
READ_POSTS = frozenset((("pfas-data-review", "download_report"),))


def read_post(name, request):
    """True when the POST is one of READ_POSTS."""
    form = getattr(request, "form", None) or {}
    action = form.get("action") if hasattr(form, "get") else None
    if isinstance(action, (list, tuple)):
        action = action[0] if action else None
    return (name, action) in READ_POSTS


def listing_read(published):
    """True when the request is a PFAS listing reading its rows."""
    view = getattr(published, "__self__", published)
    sub = list(getattr(view, "traverse_subpath", None) or [])
    return len(sub) == 1 and sub[0] in LISTING_READS


def is_staff(context):
    return _has_any_role(context, STAFF_ROLES)


def may_write(context):
    """Whether a staff user holds a role that may change something (any staff
    role but the inspector's)."""
    return _has_any_role(context, WRITE_STAFF_ROLES)


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


# core's client pages: a client and the list of clients
CLIENT_PAGE_TYPES = frozenset(("Client", "ClientFolder"))


def _published_context(published):
    """The object a published page shows: a view's context, else the
    object a method belongs to, else a skin template's container."""
    obj = getattr(published, "__self__", published)
    ctx = getattr(obj, "context", None)
    if ctx is not None:
        return ctx
    try:
        from Acquisition import aq_base, aq_inner, aq_parent
    except ImportError:                                     # Python 3 (tests)
        return obj
    if getattr(aq_base(obj), "portal_type", None):
        return obj
    return aq_parent(aq_inner(obj))


def client_sent_to_tracker(request):
    """True when a signed-in user without a lab role opens one of core's
    client pages: they are sent to the tracker, the client's own page. Staff,
    a signed-out visitor and a POST are left to core."""
    if (request.get("REQUEST_METHOD") or "GET").upper() not in ("GET", "HEAD"):
        return False
    if getattr(_published_context(request.get("PUBLISHED")), "portal_type", None) not in CLIENT_PAGE_TYPES:
        return False
    if _is_anonymous():
        return False
    portal = _portal()
    return portal is not None and not is_staff(portal)


def keep_clients_out(event):
    """IPubAfterTraversal: a visitor who is not signed in reaches only the
    public PFAS pages (ANON_VIEWS) -- any other, read or write, sends them to
    sign in; a signed-in user who holds no lab role (a client) is refused
    every PFAS staff page and the JSON API, and is sent from core's client
    pages to the tracker; an inspector-only user posts to
    none of them; the configuration pages core leaves to LabClerk are the
    manager's (MANAGER_VIEWS); and no PFAS page
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
    # core's own client pages are the lab's view of a client: a signed-in
    # client opening one is sent to their own page, the tracker
    if not name.startswith("pfas-") and client_sent_to_tracker(request):
        from zExceptions import Redirect
        raise Redirect(_portal().absolute_url() + "/@@pfas-track")
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
        if (name in CLIENT_WRITE_VIEWS and (request.get("REQUEST_METHOD") or "").upper() == "POST"
                and is_staff(_portal()) and not may_write(_portal())):
            from zExceptions import Forbidden
            raise Forbidden("This account is read-only.")
        return
    portal = _portal()
    if portal is not None and is_staff(portal):
        if ((request.get("REQUEST_METHOD") or "").upper() == "POST"
                and not may_write(portal) and not listing_read(request.get("PUBLISHED"))
                and not read_post(name, request)):
            from zExceptions import Forbidden
            raise Forbidden("This account is read-only.")
        if (name in MANAGER_VIEWS and not require_manager(portal)
                and not inspector_reads(name, request, portal)):
            from zExceptions import Forbidden
            raise Forbidden("This configuration page is for lab managers.")
        # recording or reviewing data needs a Lab Contact, initials and a
        # signature (entry_rights.py); no override
        if (request.get("REQUEST_METHOD") or "").upper() == "POST" and not read_post(name, request):
            why = data_entry_refusal(name)
            if why:
                # a person submitting a form is shown why, with the way to
                # People & Roles; a script or the JSON interface gets a 403
                if "text/html" in (request.get_header("Accept") or ""):
                    from zExceptions import Redirect
                    raise Redirect(_portal().absolute_url() + "/@@pfas-entry-refused")
                from zExceptions import Forbidden
                raise Forbidden(why)
        return
    from zExceptions import Unauthorized
    raise Unauthorized("This page is for laboratory staff.")


def inspector_reads(name, request, portal):
    """True when the inspector opens one of the manager's pages it may read
    (INSPECTOR_READ_VIEWS) by GET."""
    return (name in INSPECTOR_READ_VIEWS
            and (request.get("REQUEST_METHOD") or "GET").upper() in ("GET", "HEAD")
            and _has_any_role(portal, READ_ONLY_STAFF_ROLES))


def data_entry_refusal(name):
    """Why a POST to this page is refused for the current user (a data-entry
    or review page, and no Lab Contact, initials or signature), else None."""
    from senaite.pfas import entry_rights
    if name not in entry_rights.DATA_ENTRY_VIEWS:
        return None
    from senaite.pfas.browser.staff import is_automation, may_enter
    if entry_rights.exempt(name, is_automation()):
        return None
    return None if may_enter() else entry_rights.REFUSAL


def signed_in_name(context):
    """The signed-in person's full name, else their id, else ""."""
    try:
        m = context.portal_membership.getAuthenticatedMember()
        return m.getProperty("fullname") or m.getId()
    except Exception:                                   # noqa: BLE001
        return u""


def user_fullname(portal, user):
    """`user`'s full name from the membership tool, else their user name."""
    from Products.CMFCore.utils import getToolByName
    mt = getToolByName(portal, "portal_membership", None)
    if mt:
        member = mt.getMemberById(user.getId())
        if member:
            full = member.getProperty("fullname", "")
            if full:
                return full
    return user.getUserName() or user.getId() or "Unknown"


def user_roles_at(portal, user):
    """`user`'s roles in the portal's context."""
    try:
        return list(user.getRolesInContext(portal))
    except Exception:                                   # noqa: BLE001
        return list(user.getRoles())


def _portal():
    try:
        from bika.lims import api
        return api.get_portal()
    except Exception:                                       # noqa: BLE001
        return None
