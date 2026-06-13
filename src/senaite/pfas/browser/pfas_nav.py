# -*- coding: utf-8 -*-
"""Dashboard tiles viewlet and Worksheet/AR sub-tab views for PFAS features."""
from __future__ import print_function

from bika.lims.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.layout.viewlets.common import ViewletBase
from Products.CMFCore.utils import getToolByName

from senaite.pfas.browser.sample_status import _compute_stage, STAGES
from senaite.pfas.tracking_store import get_tracking_by_ar_uid


def _portal_url(context):
    portal = getToolByName(context, 'portal_url')
    return portal()


class PFASDashboardTilesViewlet(ViewletBase):
    """Renders a PFAS Tools section on the SENAITE dashboard."""

    index = ViewPageTemplateFile('templates/pfas_dashboard_tiles.pt')

    TILES = [
        {
            'id':    'batch-status',
            'title': 'Batch Status',
            'desc':  'Five-stage progress for every active worksheet',
            'view':  '@@pfas-sample-status',
            'icon':  'fa-tasks',
        },
        {
            'id':    'control-charts',
            'title': 'Control Charts',
            'desc':  'Levey-Jennings + Westgard multi-rule charts',
            'view':  '@@pfas-control-chart',
            'icon':  'fa-chart-line',
        },
        {
            'id':    'calibrations',
            'title': 'Calibrations',
            'desc':  'Calibration curve verification and sign-off',
            'view':  '@@pfas-calibrations',
            'icon':  'fa-sliders-h',
        },
        {
            'id':    'method-profiles',
            'title': 'Method Profiles',
            'desc':  'Per-method QC acceptance criteria',
            'view':  '@@pfas-method-profiles',
            'icon':  'fa-cogs',
        },
        {
            'id':    'qc-rules',
            'title': 'QC Rules',
            'desc':  'Toggle and configure QC rule library',
            'view':  '@@pfas-qc-rules',
            'icon':  'fa-toggle-on',
        },
        {
            'id':    'sample-tracker',
            'title': 'Sample Tracker',
            'desc':  'Public client-facing sample progress lookup',
            'view':  '@@pfas-track',
            'icon':  'fa-map-marker-alt',
        },
        {
            'id':    'setup-refs',
            'title': 'Setup Ref Defs',
            'desc':  'Sync PFAS QC criteria to SENAITE Reference Definitions',
            'view':  '@@pfas-setup-references',
            'icon':  'fa-sync-alt',
        },
    ]

    def portal_url(self):
        return _portal_url(self.context)

    def tiles(self):
        base = _portal_url(self.context)
        result = []
        for t in self.TILES:
            item = dict(t)
            item['url'] = '{0}/{1}'.format(base, t['view'])
            result.append(item)
        return result


class PFASWorksheetStageTabView(BrowserView):
    """Sub-tab view on a Worksheet showing PFAS stage + responsible person."""

    template = ViewPageTemplateFile('templates/pfas_ws_stage_tab.pt')

    def __call__(self):
        return self.template()

    def portal_url(self):
        return _portal_url(self.context)

    def stage_info(self):
        ws = self.context
        wf_tool = getToolByName(ws, 'portal_workflow')
        ws_state = wf_tool.getInfoFor(ws, 'review_state', '')
        try:
            stage, responsible = _compute_stage(ws)
        except Exception:
            return {
                'stage':       0,
                'stage_label': 'Unknown',
                'responsible': '',
                'ws_state':    ws_state,
            }
        return {
            'stage':       stage,
            'stage_label': dict(STAGES).get(stage, ''),
            'responsible': responsible,
            'ws_state':    ws_state,
        }


class PFASARTrackerTabView(BrowserView):
    """Sub-tab view on an AnalysisRequest showing tracking number + stage."""

    template = ViewPageTemplateFile('templates/pfas_ar_tracker_tab.pt')

    def __call__(self):
        return self.template()

    def portal_url(self):
        return _portal_url(self.context)

    def tracker_info(self):
        ar = self.context
        ar_uid = ar.UID()
        portal_tool = getToolByName(ar, 'portal_url')
        portal = portal_tool.getPortalObject()
        tracking_number = get_tracking_by_ar_uid(portal, ar_uid)
        tracker_url = ''
        if tracking_number:
            tracker_url = '{0}/@@pfas-track?t={1}'.format(
                _portal_url(self.context), tracking_number)
        return {
            'tracking_number': tracking_number or '',
            'tracker_url':     tracker_url,
            'ar_id':           ar.getId(),
        }
