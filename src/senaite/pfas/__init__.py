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
    from senaite.pfas import log_filters
    log_filters.install()
    # a failure here leaves SENAITE's dates in UTC; the add-on still loads
    try:
        from senaite.pfas import core_dates
        core_dates.install()
    except Exception:
        logger.error("could not show SENAITE's dates in the laboratory's time zone",
                     exc_info=True)
