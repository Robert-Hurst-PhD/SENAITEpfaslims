# -*- coding: utf-8 -*-
"""
PFAS shared page-chrome macros view.

Registered at @@pfas-macros.  All PFAS full-page templates access the
shared METAL macro via:

    metal:use-macro="context/@@pfas-macros/macros/page"

The macro defines slots:
  title          -- <title> element text (browser tab)
  head-extra     -- additional <head> content (scripts, page-specific <style>)
  header-title   -- <h1> inner content
  header-right   -- badge / back-link area to the right of the h1
  content        -- the main page body
  left-panel     -- left-panel nav (default: role-scoped via get_nav_items)

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.sidebar import _get_user_roles, sidebar_landing, sidebar_pins_json


class PFASMacrosView(BrowserView):
    """Exposes pfas_macros.pt macros for use by other PFAS page templates."""

    _template = ViewPageTemplateFile("templates/pfas_macros.pt")
    _sidebar_template = ViewPageTemplateFile("templates/pfas_sidebar.pt")

    @property
    def macros(self):
        return self._template.macros

    def print_settings(self):
        """Print header/footer settings for the shared printhead macro —
        single source: Configuration → Print Settings."""
        import datetime
        from senaite.pfas.print_settings import get_print_settings
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        ps = get_print_settings(portal)
        ps["print_date"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        return ps

    def signoff_signers(self):
        """QAO + Laboratory Director attestation signers for the shared
        `signoff` macro — single source: Configuration → Print Settings."""
        from senaite.pfas.print_settings import get_signoff_signers
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        return get_signoff_signers(portal)

    def signature_for_initials(self, initials):
        """Staff dict (fullname, signature_url, job_title, ...) for the person
        with these initials, or None — used by the sign-off macro to stamp the
        preparer's signature. Reuses the staff pool."""
        if not initials:
            return None
        from senaite.pfas.staff import find_by_initials
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        return find_by_initials(portal, initials)

    def portal_url(self):
        return getToolByName(self.context, 'portal_url').getPortalObject().absolute_url()

    def current_path(self):
        return self.request.get('PATH_INFO', '')

    def user_roles(self):
        return _get_user_roles(self.context)

    def landing(self):
        return sidebar_landing(self.context)

    def pins_json(self):
        return sidebar_pins_json(self.context)

    def user_name(self):
        """Return the authenticated user's login name, or '' if anonymous."""
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        name = getattr(user, 'getUserName', lambda: '')()
        return name if name and name.lower() != 'anonymous user' else ''

    def page_group(self):
        """The page group this page belongs to, for the frame's tab strip:
        {"label", "tabs": [{"href", "label", "active"}]}, or None (not in a
        group, or only one of its pages open to this person)."""
        from senaite.pfas import page_groups as pg
        here = pg.view_name(self.request.get("ACTUAL_URL") or self.request.get("URL", ""))
        group = pg.group_for(here)
        if group is None:
            return None
        tabs = pg.tabs_for(group, self.user_roles())
        if len(tabs) < 2:
            return None
        purl = self.portal_url()
        return {"label": group["label"],
                "tabs": [{"href": "%s/@@%s" % (purl, v), "label": label, "active": v == here}
                         for v, label in tabs]}

    def group_item(self, group_id):
        """The sidebar item of a page group: {"href", "active"}, or None when
        none of its pages is open to this person."""
        from senaite.pfas import page_groups as pg
        group = pg.group_by_id(group_id)
        first = pg.first_for(group, self.user_roles())
        if not first:
            return None
        here = pg.view_name(self.request.get("ACTUAL_URL") or self.request.get("URL", ""))
        return {"href": "%s/@@%s" % (self.portal_url(), first),
                "active": pg.group_for(here) is group}

    def is_manager_role(self):
        """Return True if the current user is a LabManager or Manager."""
        roles = self.user_roles()
        return 'LabManager' in roles or 'Manager' in roles

    # The language selector left the top bar: the site
    # language is one setting in Lab Settings.

    # (label, url path, roles that may create it) -- the "+" menu. Each target
    # is the page that already creates the thing; ?new= opens its form.
    _CREATE = [
        (u"Sample", "samples/ar_add?ar_count=1",
         ("LabClerk", "Analyst", "LabManager", "Manager", "Sampler")),
        (u"Batch", "batches/createObject?type_name=Batch", ("LabClerk", "LabManager", "Manager")),
        (u"Reagent lot", "@@pfas-reagents?new=1", ("LabClerk", "Analyst", "LabManager", "Manager")),
        (u"Prepared standard", "@@pfas-prep-standards?new=1",
         ("LabClerk", "Analyst", "LabManager", "Manager")),
        (u"Deviation", "@@pfas-deviations?new=deviation",
         ("LabClerk", "Analyst", "Verifier", "LabManager", "Manager")),
        (u"Equipment", "bika_setup/bika_instruments/createObject?type_name=Instrument",
         ("LabManager", "Manager")),
    ]

    _USER_ICONS = {"site-setup": u"fa-wrench", "my-organization": u"fa-building",
                   "user-profile": u"fa-user-cog", "logout": u"fa-sign-out-alt"}

    def terminal(self):
        """This browser is a registered lab terminal: the bar
        offers Switch user and signs out after 10 minutes idle."""
        if not hasattr(self, "_terminal"):
            try:
                from senaite.pfas.browser.badges import terminal_from_request
                self._terminal = terminal_from_request(self.request)
            except Exception:                               # noqa: BLE001
                self._terminal = None
        return self._terminal

    def terminal_idle(self):
        if not self.terminal():
            return None
        from senaite.pfas.browser.badges import IDLE_SECONDS
        return str(IDLE_SECONDS)

    def user_actions(self):
        """The user menu: Plone's `user` actions, as core's personal bar shows
        them (Site Setup for managers, My Organization for client contacts,
        My Profile, Log out) -- the top bar must not offer less than core's."""
        # The same source core's toolbar uses (PersonalBarViewlet): its hrefs
        # are evaluated for this context. plone_context_state.actions() handed
        # back unevaluated Expressions on a sample's views.
        from plone.app.layout.viewlets.common import PersonalBarViewlet
        bar = PersonalBarViewlet(self.context, self.request, self, None)
        bar.update()
        acts = [{"id": a.get("id"), "title": a.get("title"), "url": a.get("href")}
                for a in bar.user_actions or []]
        out = []
        for a in acts or []:
            aid = (a.get("id") or u"").replace(u"personaltools-", u"")
            if aid == u"logout":
                purl = getToolByName(self.context, "portal_url")()
                # every signed-in person's own signature, badge and
                # permissions, just before Log out
                out.append({"id": u"pfas-profile", "title": u"Profile & signature",
                            "url": u"%s/@@pfas-my-profile" % purl, "icon": u"fa-signature"})
                if self.terminal():
                    out.append({"id": u"pfas-switch", "title": u"Switch user (scan badge)",
                                "url": u"%s/@@pfas-badge-signin" % purl, "icon": u"fa-id-badge"})
            out.append({"id": aid, "title": a.get("title") or aid, "url": a.get("url") or u"#",
                        "icon": self._USER_ICONS.get(aid, u"fa-user")})
        return out

    def create_items(self):
        roles = set(self.user_roles())
        base = self.portal_url()
        return [{"label": label, "url": u"%s/%s" % (base, path)}
                for label, path, allowed in self._CREATE if roles & set(allowed)]

    def user_initials(self):
        """Two letters for the avatar: the full name's initials, else the
        login's first two letters."""
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        try:
            full = (user.getProperty("fullname") or u"").strip()
        except Exception:                                   # noqa: BLE001
            full = u""
        parts = [p for p in full.replace(u".", u" ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        name = full or self.user_name() or u"?"
        return name[:2].upper()

    # Views intentionally accessible without authentication.
    _PUBLIC_VIEWS = frozenset(["@@pfas-track"])

    def require_login(self):
        """Redirect anonymous users to the login form.

        Called from pfas_macros.pt before any rendering so all PFAS pages
        behave consistently on session timeout.  Raises zExceptions.Redirect
        which ZPublisher converts to a clean 302 without rendering the page.
        The came_from parameter lets Plone return the user to the page they
        were trying to reach after they authenticate.
        Views in _PUBLIC_VIEWS are exempt (e.g. the Client Tracker).
        """
        path = self.request.get("PATH_INFO", "")
        if any(v in path for v in self._PUBLIC_VIEWS):
            return
        mt = getToolByName(self.context, "portal_membership", None)
        if mt and mt.isAnonymousUser():
            from zExceptions import Redirect
            came_from = self.request.get("ACTUAL_URL", "")
            qs = self.request.get("QUERY_STRING", "")
            if qs:
                came_from = came_from + "?" + qs
            login_url = u"{0}/login_form?came_from={1}".format(
                self.portal_url(), came_from
            )
            raise Redirect(login_url)

    def render_sidebar(self):
        """Return the unified sidebar HTML fragment.

        Called from pfas_macros.pt via context/@@pfas-macros/render_sidebar.
        Renders the sidebar template with view=PFASMacrosView (so
        view/portal_url and view/current_path are available). Called as a
        method, not as a top-level response, so Plone's transform pipeline
        does not wrap the output in <!DOCTYPE html>.
        """
        return self._sidebar_template()

    def get_nav_items(self):
        """Return role-scoped left-panel nav items.

        Called via ``context/@@pfas-macros/get_nav_items`` in the macro so
        that traversal always lands on PFASMacrosView, not the calling view.
        Each entry is a dict with 'type' ('section' or 'item') plus keys
        appropriate to that type.
        """
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        base = portal.absolute_url()
        path_info = self.request.get('PATH_INFO', '')

        user = getSecurityManager().getUser()
        try:
            roles = list(user.getRolesInContext(portal))
        except Exception:
            roles = list(user.getRoles())

        def sec(title):
            return {'type': 'section', 'title': title}

        def itm(view_name, label, icon):
            url = '{0}/{1}'.format(base, view_name)
            return {
                'type': 'item',
                'url': url,
                'label': label,
                'icon': icon,
                'active': view_name in path_info,
            }

        is_manager = 'LabManager' in roles or 'Manager' in roles
        is_analyst = 'Analyst' in roles or 'Verifier' in roles
        is_clerk   = 'LabClerk' in roles

        items = [sec('Lab Tools')]

        if is_manager or is_analyst:
            items.append(itm('@@pfas-data-review',     'Data Review',     u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-method-profiles', 'Method Profiles', u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-control-chart',   'Control Charts',  u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-qc-rules',        'QC Rules',        u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-calibrations',    'Calibration Archive', u'·'))
        if is_manager or is_analyst or is_clerk:
            items.append(itm('@@pfas-sample-status',   'Batch Status',    u'·'))
        if is_manager:
            items.append(itm('@@pfas-import-studio',   'Import Studio',   u'·'))
        if is_manager or is_clerk:
            items.append(itm('@@pfas-reagents',        'Reagent Inventory', u'·'))
        if is_manager:
            items.append(itm('@@pfas-edd-batches',     'EDD Export',      u'·'))
        items.append(    itm('@@pfas-track',           'Sample Tracker',  u'·'))

        return items


# ── the site icon on core pages ────────────────────────────────
from plone.app.layout.links.viewlets import FaviconViewlet as _FaviconBase  # noqa: E402


class PFASFaviconViewlet(_FaviconBase):
    """senaite.core's plone.links.favicon, with the lab's pixel-art icon
    (tools/make_login_art.py), so core and PFAS pages share one icon."""
    _template = ViewPageTemplateFile("templates/favicon_viewlet.pt")
