# -*- coding: utf-8 -*-
"""
Event subscriber — assigns a PFAS tracking number when a sample is received.

Fires on DCWorkflow IAfterTransitionEvent for the SENAITE 'receive' transition
on AnalysisRequest objects.  Uses get_or_assign_tracking() so retract/re-receive
cycles return the same tracking number rather than minting a new one.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName

from ..tracking_store import get_or_assign_tracking

logger = logging.getLogger('senaite.pfas.browser.tracking')


def on_after_transition(instance, event):
    """Assign a PF-YYMMDD-XXXX tracking number on AR receipt."""
    if event.transition is None:
        return
    if event.transition.id != 'receive':
        return
    if getattr(instance, 'portal_type', '') != 'AnalysisRequest':
        return

    try:
        portal = getToolByName(instance, 'portal_url').getPortalObject()
        tracking_number = get_or_assign_tracking(portal, instance)
        if tracking_number:
            logger.info('AR %s received — tracking: %s',
                        instance.getId(), tracking_number)
    except Exception as exc:
        logger.error('Failed to assign tracking number to %s: %s',
                     instance.getId(), exc)
