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
from senaite.pfas.browser.sidebar import _get_user_roles


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

    def user_name(self):
        """Return the authenticated user's login name, or '' if anonymous."""
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        name = getattr(user, 'getUserName', lambda: '')()
        return name if name and name.lower() != 'anonymous user' else ''

    def is_manager_role(self):
        """Return True if the current user is a LabManager or Manager."""
        roles = self.user_roles()
        return 'LabManager' in roles or 'Manager' in roles

    def render_language_items(self):
        """Return pre-built HTML for the language dropdown.

        Builds the items in Python to avoid Chameleon macro scope issues
        where tal:repeat loop variables are inaccessible in python: expressions
        inside the macro body. Returns empty string when only one language is
        configured (caller hides the button via render_lang_available()).
        """
        lt = getToolByName(self.context, 'portal_languages', None)
        if lt is None:
            return u''
        supported = lt.getSupportedLanguages()
        if not lt.showSelector() or len(supported) <= 1:
            return u''
        try:
            bound = lt.getLanguageBindings(self.request)
            current = bound[0] if bound else ''
        except Exception:
            current = ''
        base = self.request.get('ACTUAL_URL', self.portal_url())
        qs = self.request.get('QUERY_STRING', '')
        params_base = [p for p in qs.split('&')
                       if p and not p.startswith('set_language')]
        languages = []
        for code, info in lt.getAvailableLanguageInformation().items():
            if not info.get('selected'):
                continue
            entry = dict(info)
            entry['code'] = code
            entry['active'] = code == current
            languages.append(entry)

        def _idx(entry):
            try:
                return supported.index(entry['code'])
            except ValueError:
                return len(supported)

        languages = sorted(languages, key=_idx)
        parts = []
        for lang in languages:
            name = lang.get('native') or lang.get('name', lang['code'])
            params = params_base + ['set_language={0}'.format(lang['code'])]
            url = u'{0}?{1}'.format(base, '&'.join(params))
            css = (u'pfas-hdr-useritem pfas-hdr-langactive'
                   if lang['active'] else u'pfas-hdr-useritem')
            parts.append(
                u'<a href="{0}" class="{1}">{2}</a>'.format(url, css, name)
            )
        return u''.join(parts)

    def render_lang_available(self):
        """Return True when more than one language is configured."""
        lt = getToolByName(self.context, 'portal_languages', None)
        if lt is None:
            return False
        return lt.showSelector() and len(lt.getSupportedLanguages()) > 1

    def render_section_items(self):
        """Return pre-built HTML for the global sections dropdown.

        Queries portal_tabs_view.topLevelTabs() — the same source used by
        the core SENAITE toolbar — so the PFAS apps-grid always matches core.
        Built in Python to avoid Chameleon macro scope issues with tal:repeat.
        """
        try:
            from zope.component import getMultiAdapter
            view = getMultiAdapter(
                (self.context, self.request), name='portal_tabs_view'
            )
            tabs = view.topLevelTabs()
        except Exception:
            tabs = []
        parts = []
        for tab in tabs:
            name = tab.get('name') or tab.get('title', '')
            url = tab.get('url', '#')
            parts.append(
                u'<a href="{0}" class="pfas-hdr-useritem">{1}</a>'.format(
                    url, name
                )
            )
        return u''.join(parts)

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
            items.append(itm('@@pfas-calibrations',    'Calibrations',    u'·'))
        if is_manager or is_analyst or is_clerk:
            items.append(itm('@@pfas-sample-status',   'Batch Status',    u'·'))
        if is_manager:
            items.append(itm('@@pfas-import-studio',   'Import Studio',   u'·'))
        if is_manager or is_clerk:
            items.append(itm('@@pfas-reagents',        'Reagent Inventory', u'·'))
        if is_manager:
            items.append(itm('@@pfas-egad-batches',    'EGAD EDD',        u'·'))
        items.append(    itm('@@pfas-track',           'Sample Tracker',  u'·'))

        return items
