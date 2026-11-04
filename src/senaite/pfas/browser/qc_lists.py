# -*- coding: utf-8 -*-
"""The QC store's analyst and instrument lists, for the pages that filter
by them (Control Charts, the Calibration Archive)."""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas")


class StoreListsMixin(object):
    """A view with `db_available` and `_store()`."""

    def analysts(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_analysts()
        except Exception as e:                              # noqa: BLE001
            logger.error("analysts: %s", e)
            return []

    def instruments(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_instruments()
        except Exception as e:                              # noqa: BLE001
            logger.error("instruments: %s", e)
            return []
