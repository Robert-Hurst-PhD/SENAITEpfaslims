# -*- coding: utf-8 -*-
"""Worksheet and sample sub-tab views for PFAS features."""
from __future__ import print_function

from bika.lims.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.CMFCore.utils import getToolByName

from senaite.pfas.browser.sample_status import _compute_stage, STAGES
from senaite.pfas.tracking_store import tracking_for
from senaite.pfas.browser.formutil import flatten_form


def _portal_url(context):
    portal = getToolByName(context, 'portal_url')
    return portal()


class PFASWorksheetStageTabView(BrowserView):
    """Sub-tab view on a Worksheet showing PFAS stage + responsible person."""

    template = ViewPageTemplateFile('templates/pfas_ws_stage_tab.pt')

    def __call__(self):
        flatten_form(self.request)
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
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return _portal_url(self.context)

    def tracker_info(self):
        ar = self.context
        portal_tool = getToolByName(ar, 'portal_url')
        portal = portal_tool.getPortalObject()
        # a retest shares the slip of the sample it re-analyses
        tracking_number, holder = tracking_for(portal, ar)
        tracker_url = ''
        if tracking_number:
            tracker_url = '{0}/@@pfas-track?t={1}'.format(
                _portal_url(self.context), tracking_number)
        return {
            'tracking_number': tracking_number or '',
            'tracker_url':     tracker_url,
            'ar_id':           ar.getId(),
            'held_by':         holder.getId() if holder is not None and holder.UID() != ar.UID() else '',
        }
