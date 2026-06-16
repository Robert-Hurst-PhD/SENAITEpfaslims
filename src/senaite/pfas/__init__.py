# -*- coding: utf-8 -*-
"""senaite.pfas -- PFAS LIMS extension for SENAITE."""
import logging
from zope.i18nmessageid import MessageFactory

PRODUCT_NAME = "senaite.pfas"
PROFILE_ID = "profile-senaite.pfas:default"
logger = logging.getLogger(PRODUCT_NAME)
messageFactory = MessageFactory(PRODUCT_NAME)


def initialize(context):
    logger.info("*** Initializing senaite.pfas ***")
