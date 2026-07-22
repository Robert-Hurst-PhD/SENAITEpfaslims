# -*- coding: utf-8 -*-
from senaite.core.interfaces import ISenaiteCore
from bika.lims.interfaces import IBikaLIMS


class ISenaitePFASLayer(ISenaiteCore, IBikaLIMS):
    """Browser layer for senaite.pfas.

    Registered via browserlayer.xml so all requests to a SENAITE site
    with this add-on installed are marked with this interface.  It extends
    BOTH core browser layers — ISenaiteCore AND IBikaLIMS (which are
    independent, neither derives from the other) — so a view registered on
    this layer is strictly more specific than a core view registered on either
    one, and wins adapter lookup without a ZCML conflict.  This is how we
    override @@lims-setup (on ISenaiteCore) and @@email (on IBikaLIMS, D63)
    with plain <include>, no includeOverrides / global replace.
    """
