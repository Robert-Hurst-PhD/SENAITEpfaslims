# -*- coding: utf-8 -*-
"""
PFAS Client Tracker (@@pfas-track) — public no-login sample tracking page.

Clients enter their PF-YYMMDD-XXXX tracking number to see their sample's
progress through the five PFAS lab stages, along with a 16-bit scientist
animation and a per-stage time estimate from historical averages.

Security model
--------------
This view is registered with zope2.Public so unauthenticated clients can
access it.  All SENAITE object reads (AR, Worksheet) are done under an
elevated security context (UnrestrictedUser) so anonymous requests don't
hit Unauthorized.  Only a minimal public-safe dict is returned to the
template — no analyst names, sample IDs, internal IDs, or QC data.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import re

from AccessControl.SecurityManagement import (
    getSecurityManager, newSecurityManager, setSecurityManager)
from AccessControl.User import UnrestrictedUser as _UnrestrictedUser
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from ..tracking_store import get_ar_uid_by_tracking
from .sample_status import (
    STAGES, _build_stage_steps, _compute_stage, _get_method_name,
)
from .stage_estimates import format_estimate, get_stage_estimates

logger = logging.getLogger('senaite.pfas.browser.tracker')

_TRACKING_RE = re.compile(r'^PF-\d{6}-[A-Z0-9]{4}$')

# ── Stage SVG animations (16-bit pixel-art style) ────────────────────────────
# Each is a standalone SVG embedded directly in the tracker page.
# Characters and props use blocky shapes with a limited palette to evoke
# a 16-bit look.  CSS keyframe animations run entirely in the browser.

_SVG_STAGE1 = u"""\
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<style>
.sci{animation:bob 1.4s ease-in-out infinite;}
.box{animation:slide 1.4s ease-in-out infinite;}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
@keyframes slide{0%,100%{transform:translateX(0)}50%{transform:translateX(4px)}}
</style>
<rect width="120" height="120" fill="#b3e5fc"/>
<rect y="100" width="120" height="20" fill="#81d4fa"/>
<g class="sci">
  <rect x="50" y="32" width="20" height="8" rx="3" fill="#4e342e"/>
  <rect x="50" y="36" width="20" height="20" rx="4" fill="#ffcc80"/>
  <rect x="54" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="62" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="56" y="50" width="8" height="3" rx="1" fill="#ff8a65"/>
  <rect x="46" y="56" width="28" height="32" rx="2" fill="#eceff1"/>
  <rect x="50" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="63" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="34" y="58" width="12" height="7" rx="3" fill="#eceff1" transform="rotate(-25 40 61)"/>
  <rect x="74" y="58" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="30" y="50" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="76" y="62" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="50" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="62" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="46" y="100" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="60" y="100" width="16" height="8" rx="3" fill="#212121"/>
</g>
<g class="box">
  <rect x="12" y="66" width="28" height="28" rx="2" fill="#ffe0b2"/>
  <rect x="12" y="66" width="28" height="9" rx="2" fill="#ff8f00"/>
  <rect x="24" y="66" width="4" height="28" fill="#ff8f00"/>
  <rect x="16" y="79" width="7" height="3" rx="1" fill="#fff9c4"/>
  <rect x="16" y="84" width="7" height="3" rx="1" fill="#fff9c4"/>
</g>
</svg>"""

_SVG_STAGE2 = u"""\
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<style>
.sci{animation:bob 1.2s ease-in-out infinite;}
.flask{animation:swirl 2s ease-in-out infinite;}
.bub{animation:bubble 1.6s ease-in-out infinite;}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@keyframes swirl{0%,100%{transform:rotate(-6deg)}50%{transform:rotate(6deg)}}
@keyframes bubble{0%,100%{opacity:1;transform:translateY(0)}50%{opacity:0.4;transform:translateY(-4px)}}
</style>
<rect width="120" height="120" fill="#fff3e0"/>
<rect y="100" width="120" height="20" fill="#ffcc80"/>
<rect x="14" y="86" width="30" height="14" rx="2" fill="#90a4ae"/>
<rect x="16" y="82" width="26" height="6" rx="2" fill="#78909c"/>
<rect x="24" y="88" width="10" height="8" fill="#e53935" opacity="0.7"/>
<g class="sci">
  <rect x="50" y="32" width="20" height="8" rx="3" fill="#4e342e"/>
  <rect x="50" y="36" width="20" height="20" rx="4" fill="#ffcc80"/>
  <rect x="54" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="62" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="56" y="50" width="8" height="3" rx="1" fill="#ff8a65"/>
  <rect x="46" y="56" width="28" height="32" rx="2" fill="#eceff1"/>
  <rect x="50" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="63" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="74" y="58" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="34" y="56" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="76" y="62" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="50" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="62" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="46" y="100" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="60" y="100" width="16" height="8" rx="3" fill="#212121"/>
</g>
<g class="flask" style="transform-origin:38px 88px">
  <rect x="32" y="56" width="12" height="4" rx="2" fill="#78909c"/>
  <rect x="33" y="60" width="10" height="18" rx="2" fill="#e0f7fa" stroke="#78909c" stroke-width="1.5"/>
  <rect x="29" y="78" width="18" height="16" rx="6" fill="#e0f7fa" stroke="#78909c" stroke-width="1.5"/>
  <rect x="30" y="84" width="16" height="8" rx="4" fill="#4fc3f7" opacity="0.7"/>
  <rect x="33" y="61" width="4" height="14" rx="2" fill="#b2ebf2" opacity="0.7"/>
  <circle class="bub" cx="37" cy="80" r="2" fill="#ffffff" opacity="0.8"/>
  <circle class="bub" cx="43" cy="82" r="1.5" fill="#ffffff" opacity="0.8" style="animation-delay:0.4s"/>
</g>
</svg>"""

_SVG_STAGE3 = u"""\
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<style>
.sci{animation:bob 1.6s ease-in-out infinite;}
.screen{animation:blink 1.8s step-start infinite;}
.led{animation:blink 0.9s step-start infinite;}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
@keyframes blink{0%,60%{opacity:1}61%,100%{opacity:0.3}}
</style>
<rect width="120" height="120" fill="#fce4ec"/>
<rect y="100" width="120" height="20" fill="#f48fb1"/>
<rect x="8" y="46" width="36" height="58" rx="3" fill="#546e7a"/>
<rect x="10" y="48" width="32" height="44" rx="2" fill="#37474f"/>
<rect class="screen" x="12" y="50" width="28" height="18" rx="1" fill="#1b5e20"/>
<rect x="14" y="52" width="8" height="3" fill="#4caf50"/>
<rect x="14" y="57" width="12" height="3" fill="#4caf50" opacity="0.7"/>
<rect x="14" y="62" width="6" height="3" fill="#81c784" opacity="0.5"/>
<rect x="24" y="52" width="14" height="14" rx="1" fill="#0d47a1" opacity="0.4"/>
<rect class="screen" x="26" y="54" width="10" height="10" rx="1" fill="#1565c0"/>
<rect x="28" y="72" width="6" height="4" rx="1" fill="#78909c"/>
<rect class="led" x="36" y="72" width="5" height="4" rx="1" fill="#00e676"/>
<rect x="10" y="78" width="32" height="24" rx="2" fill="#455a64"/>
<rect x="14" y="82" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="21" y="82" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="28" y="82" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="35" y="82" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="14" y="90" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="21" y="90" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="28" y="90" width="5" height="5" rx="1" fill="#78909c"/>
<rect x="35" y="90" width="5" height="5" rx="1" fill="#78909c"/>
<g class="sci">
  <rect x="66" y="32" width="20" height="8" rx="3" fill="#4e342e"/>
  <rect x="66" y="36" width="20" height="20" rx="4" fill="#ffcc80"/>
  <rect x="70" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="78" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="72" y="50" width="8" height="3" rx="1" fill="#ff8a65"/>
  <rect x="62" y="56" width="28" height="32" rx="2" fill="#eceff1"/>
  <rect x="66" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="79" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="50" y="58" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="90" y="60" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="44" y="62" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="92" y="62" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="66" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="78" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="62" y="100" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="76" y="100" width="16" height="8" rx="3" fill="#212121"/>
</g>
</svg>"""

_SVG_STAGE4 = u"""\
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<style>
.sci{animation:lean 2s ease-in-out infinite;}
.cursor{animation:blink 1s step-start infinite;}
@keyframes lean{0%,100%{transform:translateX(0)}50%{transform:translateX(3px)}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
</style>
<rect width="120" height="120" fill="#f3e5f5"/>
<rect y="100" width="120" height="20" fill="#ce93d8"/>
<rect x="10" y="70" width="50" height="34" rx="2" fill="#37474f"/>
<rect x="12" y="72" width="46" height="26" rx="1" fill="#1a237e"/>
<rect x="14" y="74" width="6" height="20" fill="#3949ab" opacity="0.6"/>
<rect x="14" y="74" width="4" height="20" fill="#3949ab" opacity="0.4"/>
<polyline points="14,88 20,80 26,86 32,76 38,82 44,74 50,78 56,72" fill="none" stroke="#7c4dff" stroke-width="2"/>
<rect x="14" y="74" width="6" height="20" fill="#3949ab" opacity="0.3"/>
<rect class="cursor" x="55" y="72" width="3" height="16" fill="#e040fb"/>
<rect x="18" y="98" width="34" height="4" rx="2" fill="#546e7a"/>
<rect x="28" y="100" width="14" height="3" rx="1" fill="#607d8b"/>
<rect x="10" y="104" width="50" height="6" rx="2" fill="#455a64"/>
<g class="sci">
  <rect x="70" y="32" width="20" height="8" rx="3" fill="#4e342e"/>
  <rect x="70" y="36" width="20" height="20" rx="4" fill="#ffcc80"/>
  <rect x="74" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="82" y="42" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="73" y="50" width="10" height="3" rx="1" fill="#ff8a65"/>
  <rect x="66" y="56" width="28" height="32" rx="2" fill="#eceff1"/>
  <rect x="70" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="83" y="60" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="54" y="60" width="12" height="7" rx="3" fill="#eceff1" transform="rotate(-20 60 64)"/>
  <rect x="94" y="60" width="12" height="7" rx="3" fill="#eceff1"/>
  <rect x="50" y="66" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="96" y="62" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="70" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="82" y="88" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="66" y="100" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="80" y="100" width="16" height="8" rx="3" fill="#212121"/>
</g>
</svg>"""

_SVG_STAGE5 = u"""\
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<style>
.sci{animation:jump 1.4s ease-in-out infinite;}
.doc{animation:wave 1.4s ease-in-out infinite;}
.star{animation:twinkle 1s ease-in-out infinite;}
.star2{animation:twinkle 1s ease-in-out infinite;animation-delay:0.3s;}
.star3{animation:twinkle 1s ease-in-out infinite;animation-delay:0.6s;}
@keyframes jump{0%,100%{transform:translateY(0)}40%{transform:translateY(-10px)}60%{transform:translateY(-10px)}}
@keyframes wave{0%,100%{transform:rotate(-8deg)}50%{transform:rotate(8deg)}}
@keyframes twinkle{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.2;transform:scale(0.5)}}
</style>
<rect width="120" height="120" fill="#e8f5e9"/>
<rect y="100" width="120" height="20" fill="#a5d6a7"/>
<g class="sci" style="transform-origin:60px 70px">
  <rect x="46" y="30" width="20" height="8" rx="3" fill="#4e342e"/>
  <rect x="46" y="34" width="20" height="20" rx="4" fill="#ffcc80"/>
  <rect x="50" y="40" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="58" y="40" width="4" height="4" rx="1" fill="#3e2723"/>
  <rect x="51" y="48" width="10" height="3" rx="2" fill="#ff8a65"/>
  <rect x="42" y="54" width="28" height="32" rx="2" fill="#eceff1"/>
  <rect x="46" y="58" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="59" y="58" width="7" height="7" rx="1" fill="#b0bec5"/>
  <rect x="46" y="86" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="58" y="86" width="10" height="16" rx="2" fill="#1a237e"/>
  <rect x="42" y="98" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="56" y="98" width="16" height="8" rx="3" fill="#212121"/>
  <rect x="20" y="36" width="12" height="7" rx="3" fill="#eceff1" transform="rotate(30 26 40)"/>
  <rect x="80" y="36" width="12" height="7" rx="3" fill="#eceff1" transform="rotate(-30 86 40)"/>
  <rect x="16" y="28" width="10" height="10" rx="3" fill="#ffcc80"/>
  <rect x="86" y="28" width="10" height="10" rx="3" fill="#ffcc80"/>
</g>
<g class="doc" style="transform-origin:20px 30px">
  <rect x="6" y="14" width="28" height="36" rx="2" fill="#fff9c4" stroke="#f9a825" stroke-width="1.5"/>
  <rect x="10" y="20" width="20" height="3" rx="1" fill="#f57f17"/>
  <rect x="10" y="26" width="16" height="2" rx="1" fill="#f9a825"/>
  <rect x="10" y="31" width="18" height="2" rx="1" fill="#f9a825"/>
  <rect x="10" y="36" width="14" height="2" rx="1" fill="#f9a825"/>
  <polyline points="11,42 14,46 23,38" fill="none" stroke="#2e7d32" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
</g>
<circle class="star" cx="96" cy="20" r="4" fill="#ffd54f"/>
<circle class="star2" cx="106" cy="36" r="3" fill="#ffd54f"/>
<circle class="star3" cx="88" cy="12" r="2.5" fill="#ffd54f"/>
</svg>"""

_STAGE_ANIMATIONS = {
    1: _SVG_STAGE1,
    2: _SVG_STAGE2,
    3: _SVG_STAGE3,
    4: _SVG_STAGE4,
    5: _SVG_STAGE5,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _portal(context):
    return context.portal_url.getPortalObject()


def _get_worksheet_for_ar(ar):
    """Return first Worksheet containing an analysis from *ar*, or None."""
    try:
        for brain in ar.getAnalyses():
            try:
                obj = brain if not hasattr(brain, 'getObject') else brain.getObject()
                ws = obj.getWorksheet()
                if ws is not None:
                    return ws
            except Exception:
                pass
    except Exception:
        pass
    return None


def _build_public_status(portal, ar_uid):
    """
    Compute public-safe status dict for the given AR UID.
    Must be called under elevated security context.
    Returns None if the AR cannot be found.
    """
    pc = getToolByName(portal, 'portal_catalog')
    brains = pc.unrestrictedSearchResults(UID=ar_uid)
    if not brains:
        return None

    ar = brains[0].getObject()
    stage = 1
    method_name = u''

    ws = _get_worksheet_for_ar(ar)
    if ws is not None:
        stage, _responsible = _compute_stage(ws)
        method_name = _get_method_name(ws) or u''

    stage_label = dict(STAGES).get(stage, u'')
    steps = _build_stage_steps(stage)

    estimate_text = None
    try:
        estimates = get_stage_estimates(portal, method_name)
        avg_hours = estimates.get(stage)
        if avg_hours is not None:
            estimate_text = format_estimate(avg_hours)
    except Exception as exc:
        logger.debug('Could not compute estimates: %s', exc)

    return {
        'stage':         stage,
        'stage_label':   stage_label,
        'method':        method_name,
        'steps':         steps,
        'estimate_text': estimate_text,
    }


# ── View ──────────────────────────────────────────────────────────────────────

class PFASClientTrackerView(BrowserView):
    """
    @@pfas-track — public no-login client tracking page.
    Permission: zope2.Public (see configure.zcml).
    """
    template = ViewPageTemplateFile('templates/tracker.pt')

    def __call__(self):
        return self.template()

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def tracking_number(self):
        return self.request.form.get('t', u'').strip().upper()

    def status(self):
        """
        Return public status dict, or None if tracking number not found.
        All SENAITE object reads are done under an elevated security context.
        """
        t = self.tracking_number()
        if not t or not _TRACKING_RE.match(t):
            return None

        portal = _portal(self.context)
        ar_uid = get_ar_uid_by_tracking(portal, t)
        if not ar_uid:
            return None

        old_sm = getSecurityManager()
        try:
            newSecurityManager(
                self.request,
                _UnrestrictedUser('pfas_tracker_internal', '', [], []),
            )
            return _build_public_status(portal, ar_uid)
        except Exception as exc:
            logger.error('Error computing public status for %s: %s', t, exc)
            return None
        finally:
            setSecurityManager(old_sm)

    def not_found(self):
        """True if a valid-format tracking number was submitted but has no match."""
        t = self.tracking_number()
        if not t:
            return False
        if not _TRACKING_RE.match(t):
            return False
        return self.status() is None

    def animation_svg(self):
        """Return SVG markup for the current stage's 16-bit animation."""
        s = self.status()
        if s is None:
            return u''
        return _STAGE_ANIMATIONS.get(s['stage'], u'')
