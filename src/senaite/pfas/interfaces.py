# -*- coding: utf-8 -*-
from senaite.core.interfaces import ISenaiteCore


class ISenaitePFASLayer(ISenaiteCore):
    """Browser layer for senaite.pfas.

    Registered via browserlayer.xml so all requests to a SENAITE site
    with this add-on installed are marked with this interface.  Because
    ISenaitePFASLayer extends ISenaiteCore, views registered on this layer
    take precedence over views registered on ISenaiteCore alone — which is
    how we override @@lims-setup without a ZCML conflict.
    """
