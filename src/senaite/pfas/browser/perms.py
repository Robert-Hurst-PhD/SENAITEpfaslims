# -*- coding: utf-8 -*-
"""
Shared role gate for PFAS management views.

Extracted from browser/logbooks.py so that sibling management views
(prep logbook definitions, logbook step media) can enforce the SAME rule
without importing each other — a module-level back-import between
logbooks.py and prep_logbooks.py would be a cycle waiting to happen.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

# Roles permitted to edit lab configuration (method profiles, logbook
# definitions, QC criteria). Matches CLAUDE.md §4: only Manager / QAO /
# Director / Owner may edit configuration tables.
ALLOWED_ROLES = frozenset(("Manager", "LabManager", "Owner"))

# Backwards-compatible alias — logbooks.py used this private name.
_ALLOWED_ROLES = ALLOWED_ROLES


def require_manager(context, request=None):
    """True if the current user holds a management role in this context.

    Never raises: an unauthenticated or broken security context is treated
    as "not a manager" (deny by default).
    """
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        return bool(ALLOWED_ROLES.intersection(user.getRolesInContext(context)))
    except Exception:
        return False


# Backwards-compatible alias — logbooks.py used this private name.
_require_manager = require_manager
