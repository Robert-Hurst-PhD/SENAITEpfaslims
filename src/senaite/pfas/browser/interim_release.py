# -*- coding: utf-8 -*-
"""The Interim release sign right is the authority to issue an interim
certificate.

Issuing an interim is core's prepublish of a sample whose results are
submitted, not yet verified. Core guards that transition with its Publish
Results permission (the Publisher role). An interim released at Submit is
issued by the one who signed it, on their Interim release right, with or
without that role: for that one transition, on that one sample, the
signer's security manager answers Publish Results as granted. Nothing else
is granted: no role, no other permission, no other object, and no other
publish (a final, a republish, core's Publish button) changes.

The grant is given only when everything the publish guard asks would let
the interim go (controlled_publications.signature_refusal: the signature is
the signer's own interim, still good, on a right they still hold, its image
kept, the ledger writable, the certificate sealed or on its way and
generated as interim); the guard then asks it all again in the transition.

The same right covers generating that interim: while the publisher stores
the certificate, the signer's security manager answers the sample's add
permission as granted on that one sample, the container the stored report
is created and renamed in. The conditions are the publish's, less those
on the stored certificate (sealed, generated as interim), which the
generate itself makes.

    interim_grant(state, pending, userid, refusal)  True when the grant applies
    for_sample(sample)                              the grant around one publish
    for_generate(samples)                           the grant around storing
                                                    the generated interim
    granted(permission, objects)                    the security manager grant

Python 2.7; Zope imports are made where they are used.
"""
from __future__ import absolute_import, unicode_literals

import contextlib
import logging

logger = logging.getLogger("senaite.pfas.interim_release")

# the sample's review state an interim issues from (esig.certificate)
SUBMITTED_STATE = "to_be_verified"


def interim_grant(state, pending, userid, refusal):
    """True when the publish of a sample in review `state` is an interim
    its signer issues: the pending signature is an interim, `userid`'s own,
    and the publish guard's question (`refusal`) finds nothing against it."""
    pending = pending or {}
    return bool(state == SUBMITTED_STATE and pending.get("interim") and userid
                and pending.get("userid") == userid and refusal is None)


def _base(obj):
    try:
        from Acquisition import aq_base
    except ImportError:                                     # outside Zope
        return obj
    return aq_base(obj)


class GrantedPermission(object):
    """The caller's security manager, with one permission answered as held
    on the given objects only; everything else is the caller's own."""

    def __init__(self, base, permission, objects):
        self._pfas_base = base
        self._pfas_permission = permission
        self._pfas_objects = [_base(o) for o in objects or []]

    def checkPermission(self, permission, obj):
        if permission == self._pfas_permission:
            target = _base(obj)
            if any(target is o for o in self._pfas_objects):
                return 1
        return self._pfas_base.checkPermission(permission, obj)

    def __getattr__(self, name):
        return getattr(self._pfas_base, name)


@contextlib.contextmanager
def granted(permission, objects):
    """Run the body with `permission` granted on `objects`, then put the
    caller's security manager back, error or not."""
    from AccessControl.SecurityManagement import getSecurityManager, setSecurityManager
    saved = getSecurityManager()
    setSecurityManager(GrantedPermission(saved, permission, objects))
    try:
        yield
    finally:
        setSecurityManager(saved)


@contextlib.contextmanager
def _nothing():
    yield


def _signs_interim(sample, stored):
    """True when the current user issues an interim on sample on their
    Interim release right: interim_grant over the publish guard's question
    (with or without its checks of the stored certificate). A question that
    cannot be answered is False."""
    from bika.lims import api
    from senaite.pfas.browser.controlled_publications import (
        _current_userid, pending_signature, signature_refusal)
    from ZODB.POSException import ConflictError
    try:
        state = api.get_review_status(sample)
        pending = pending_signature(sample)
        userid = _current_userid()
        if not (state == SUBMITTED_STATE and (pending or {}).get("interim")):
            return False
        refusal = signature_refusal(sample, userid) if stored else \
            signature_refusal(sample, userid, stored=False)
        return interim_grant(state, pending, userid, refusal)
    except ConflictError:
        raise                                               # Zope retries the request
    except Exception:                                       # noqa: BLE001
        # a question that cannot be answered grants nothing
        logger.warning("interim release: %s not asked", api.get_id(sample), exc_info=True)
        return False


def for_sample(sample):
    """The grant around one publish of `sample`, when it is an interim its
    signer issues on their Interim release right; otherwise nothing is
    granted and core's permission decides as before."""
    from senaite.core.permissions import TransitionPublishResults
    if not _signs_interim(sample, True):
        return _nothing()
    return granted(TransitionPublishResults, [sample])


# the permission the stored report's creation and rename ask of the sample
# it is stored in: core registers the stored report under it
ADD_PERMISSION = "Add portal content"


def for_generate(samples):
    """The grant around storing a generated certificate in `samples`: the
    add permission on each sample whose interim its signer generates on
    their Interim release right; nothing on any other sample, and nothing
    at all when there is none."""
    mine = [s for s in samples or [] if _signs_interim(s, False)]
    if not mine:
        return _nothing()
    return granted(ADD_PERMISSION, mine)
