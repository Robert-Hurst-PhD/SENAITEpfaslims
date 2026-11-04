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

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.sidebar import _get_user_roles, request_here, sidebar_nav, sidebar_pins_json


class PFASMacrosView(ViewHelpers, BrowserView):
    """Exposes pfas_macros.pt macros for use by other PFAS page templates."""

    _template = ViewPageTemplateFile("templates/pfas_macros.pt")
    _sidebar_template = ViewPageTemplateFile("templates/pfas_sidebar.pt")

    @property
    def macros(self):
        return self._template.macros

    def help_term(self, hid):
        """The term a Help button is named by (the "help" macro): its
        help_dictionary entry's, else the id itself."""
        from senaite.pfas import help_dictionary
        return help_dictionary.term_of(hid)

    def lab_name(self):
        """The laboratory's name (core's Laboratory), for the tab title."""
        from senaite.pfas import lab_identity
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        try:
            return lab_identity.read(portal)["name"]
        except Exception:                                   # noqa: BLE001
            return u""

    def asset_version(self):
        """?v= for the add-on's CSS and JS URLs (asset_version.py)."""
        from senaite.pfas.browser.asset_version import asset_version
        return asset_version()

    def data_lab_today(self):
        """The laboratory's date for the page's scripts (data-lab-today on
        its root element) while the zone converts; None otherwise, so the
        attribute is left out and a script keeps its own clock."""
        from senaite.pfas import lab_time
        return lab_time.today().isoformat() if lab_time.active() else None

    def print_settings(self):
        """Print header/footer settings for the shared printhead macro —
        single source: Configuration → Print Settings."""
        from senaite.pfas import print_doc
        from senaite.pfas.print_settings import get_print_settings
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        ps = get_print_settings(portal)
        ps["print_date"] = print_doc.now_label()
        return ps

    def print_block(self, control=None, title=None):
        """The printed header, control block and footer rule of a page.

        `control` is what a view says about itself (its `print_control`, a
        dict or a callable returning one): doc_id, revision, date, date_label,
        title, subtitle and cells, a list of extra (label, value) pairs.
        Missing parts default to the page's own title and the print date; the
        title is then read from the browser tab when the page is printed
        (pfas-print.js), because the page macro cannot see its own title slot.
        Returns {css, head, auto}.
        """
        from senaite.pfas import print_doc
        if callable(control):
            try:
                control = control()
            except Exception:                               # noqa: BLE001
                control = None
        control = dict(control or {})
        ps = self.print_settings()
        printed_at = print_doc.now_label()
        printed_by = print_doc.current_user_label(self.context)
        doc_id = control.get("doc_id") or title or u""
        cells = [(u"Document", doc_id or u"\u2026")]
        if control.get("revision") not in (None, u""):
            cells.append((u"Revision", u"%s" % control["revision"]))
        if control.get("date"):
            cells.append((control.get("date_label") or u"Effective", control["date"]))
        cells.extend(control.get("cells") or [])
        cells.append((u"Printed", printed_at))
        head = print_doc.head_html(
            ps, control.get("title") or u"", cells, subtitle=control.get("subtitle"),
            logo=True, portal_url=self.portal_url())
        issued = control.get("issued") or control.get("date")
        css = print_doc.document_css(doc_id, control.get("revision"), printed_by,
                                     printed_at, base=False, issued=issued)
        # a page named by its own title (pfas-print.js): what follows the title
        rev = u" Rev %s" % control["revision"] if control.get("revision") not in (None, u"") else u""
        foot = print_doc.css_string(rev) + u"\\A " + print_doc.css_string(
            print_doc.printed_line(printed_at, printed_by))
        return {"css": css, "head": head, "auto": not doc_id, "foot": foot}

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

    def user_roles(self):
        return _get_user_roles(self.context)

    def nav(self):
        """The rail and the section panel for this page (sidebar.sidebar_nav)."""
        return sidebar_nav(self.context, self.request, self.portal_url())

    def pins_json(self, nav):
        return sidebar_pins_json(nav)

    def user_name(self):
        """Return the authenticated user's login name, or '' if anonymous."""
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        name = getattr(user, 'getUserName', lambda: '')()
        return name if name and name.lower() != 'anonymous user' else ''

    def _here(self):
        """(path under the site, {query name: value}) of this page."""
        return request_here(self.request, self.portal_url())

    def crumb_trail(self):
        """The breadcrumb of this page, drawn from the navigation map as this
        person's tree shows it: [{"kind", "label", "url"}] from the section
        (kind "text": it has no page) down to the page. A link is "link"; the
        page itself is "here" when the last row of the map is this page, else
        its row stays a link and "title" stands for the page's own title (a
        record beneath a listed item). A page on none of the person's rows
        gets Home, then the title. [] on the dashboard, which has no place."""
        from senaite.pfas import page_groups as pg
        if self.context.portal_membership.isAnonymousUser():
            return []
        path, query = self._here()
        trail = pg.crumbs(path, query, _get_user_roles(self.context))
        if not trail:
            if pg.is_dashboard(path):
                return []
            home = pg.HOME["dashboard"]
            return [{"kind": "link", "label": pg.HOME["label"], "url": home["url_path"]},
                    {"kind": "title", "label": "", "url": None}]
        out = [{"kind": "link" if url else "text", "label": label, "url": url}
               for label, url in trail]
        if pg.same_page(trail[-1][1] or "", path) or pg.is_row_page(path):
            out[-1]["kind"] = "here"
        else:
            out.append({"kind": "title", "label": "", "url": None})
        return out

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
        view/portal_url and view/nav are available). Called as a
        method, not as a top-level response, so Plone's transform pipeline
        does not wrap the output in <!DOCTYPE html>.
        """
        return self._sidebar_template()

# ── the site icon on core pages ────────────────────────────────
from plone.app.layout.links.viewlets import FaviconViewlet as _FaviconBase  # noqa: E402


class PFASFaviconViewlet(_FaviconBase):
    """senaite.core's plone.links.favicon, with the lab's pixel-art icon
    (tools/make_login_art.py), so core and PFAS pages share one icon."""
    _template = ViewPageTemplateFile("templates/favicon_viewlet.pt")
