# -*- coding: utf-8 -*-
"""Records that are replaced keep what they replaced (ISO 17025 §7.5: a
change leaves the earlier entry legible). One rule for a correction, a
sign-off or any per-key record a newer one supersedes.

    with_earlier(prev, entry)   `entry`, carrying `prev` (and everything
                                `prev` carried) under "earlier", oldest first
    log(obj, action, reason, detail)   append one event to an object's own
                                trail: {at, who, action, reason, detail}
                                (config_history.now / actor), never edited
    events(obj)                 that trail, oldest first

with_earlier is pure (Python 2.7 and 3); log and events need Zope.
"""
from __future__ import absolute_import, unicode_literals

EARLIER = "earlier"


def with_earlier(prev, entry):
    """`entry` replacing `prev`: prev's own earlier records, then prev
    itself, are kept under "earlier" (oldest first). No prev: entry as given."""
    entry = dict(entry)
    if prev:
        kept = list(prev.get(EARLIER) or [])
        kept.append(dict((k, v) for k, v in prev.items() if k != EARLIER))
        entry[EARLIER] = kept
    return entry


LOG_KEY = "senaite.pfas.audit_log"


def log(obj, action, reason=u"", detail=None):
    """Append one event to `obj`'s audit trail (an annotation list), in the
    same shape as the configuration history's entries; it commits or rolls
    back with the change it describes."""
    import json
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.config_history import actor, now
    ann = IAnnotations(obj)
    trail = json.loads(ann.get(LOG_KEY) or u"[]")
    entry = {u"at": now(), u"who": actor(), u"action": action}
    if reason:
        entry[u"reason"] = reason
    if detail:
        entry[u"detail"] = detail
    trail.append(entry)
    ann[LOG_KEY] = json.dumps(trail)
    return entry


def events(obj):
    """`obj`'s audit trail, oldest first."""
    import json
    from zope.annotation.interfaces import IAnnotations
    return json.loads(IAnnotations(obj).get(LOG_KEY) or u"[]")
