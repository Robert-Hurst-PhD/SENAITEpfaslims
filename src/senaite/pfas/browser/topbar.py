# -*- coding: utf-8 -*-
"""The one top toolbar on every page (GAPS §93, DECISIONS 2026-10-03).

PFAS pages draw it from pfas_macros.pt; core SENAITE pages draw it because
PFASToolbarManager replaces senaite.core's toolbar viewlet manager on the PFAS
layer (overrides.zcml) -- the same upgrade-safe override PFASSidebarManager
uses. Both fill ONE macro, templates/pfas_topbar.pt, so the bar cannot differ
between a core page and a PFAS page.

Upgrade note: PFASToolbarManager subclasses
senaite.core.browser.viewlets.toolbar.ToolbarViewletManager and keeps its
base_render() (core's content views, e.g. "Audit Log"). If core renames that,
the context zone on core pages goes empty; nothing else depends on it.
"""
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.viewlets.toolbar import ToolbarViewletManager


class PFASTopbarView(BrowserView):
    """Holds the macro: context/@@pfas-topbar/macros/topbar."""

    index = ViewPageTemplateFile("templates/pfas_topbar.pt")

    @property
    def macros(self):
        return self.index.macros

    def __call__(self):
        return u""


class PFASToolbarManager(ToolbarViewletManager):
    custom_template = ViewPageTemplateFile("templates/core_topbar.pt")

    def page_title(self):
        """The title the bar shows before pfas-topbar.js swaps in the page's
        own H1: the view's title if it has one, else the object's."""
        title = getattr(self.__parent__, "title", None)
        if callable(title):
            try:
                title = title()
            except Exception:
                title = None
        if not isinstance(title, basestring) or not title.strip():  # noqa: F821 (py2)
            title = self.context_state.object_title()
        return title or u"LIMS"
