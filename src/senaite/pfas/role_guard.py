# -*- coding: utf-8 -*-
"""The role-change guard behind People & Roles.

A Lab Manager changes other people's roles here under a temporary Manager
elevation. check() holds every rule and fails closed; apply() elevates only
around the group and role calls themselves, and always restores the security
manager.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import contextlib

# (group id, role, label), in the order the page lists them.
ROLE_GROUPS = (
    ("LabManagers", "LabManager", "Lab Manager"),
    ("Analysts", "Analyst", "Analyst"),
    ("Verifiers", "Verifier", "Verifier"),
    ("LabClerks", "LabClerk", "Lab Clerk"),
    ("Samplers", "Sampler", "Sampler"),
    ("Publishers", "Publisher", "Publisher"),
    ("RegulatoryInspectors", "RegulatoryInspector", "Regulatory Inspector"),
    ("SamplingCoordinators", "SamplingCoordinator", "Sampling Coordinator"),
    ("Preservers", "Preserver", "Preserver"),
)

# The administrator roles: the site-administration tier of the action gates
# (browser/perms.SITE_ADMIN_ROLES: Manager, Owner) plus Plone's Site
# Administrator. Mirrored here so this module imports without the browser
# package; a test keeps the two equal. An account holding one is changed only
# by an administrator.
PROTECTED_ROLES = ("Manager", "Owner", "Site Administrator")

_CHANGERS = ("LabManager",) + PROTECTED_ROLES


def check(actor_id, actor_roles, target_id, target_roles, add, remove, reason):
    """The refusal text, or None when the change is allowed. Roles are the
    effective roles at the portal, groups included."""
    actor_roles = set(actor_roles or ())
    target_roles = set(target_roles or ())
    # 1. only a Lab Manager (or an administrator) changes roles
    if not actor_roles.intersection(_CHANGERS):
        return u"Only a Lab Manager changes roles."
    # 2. only the groups listed above can be added or removed
    known = set(g for g, _r, _l in ROLE_GROUPS)
    if (set(add or ()) | set(remove or ())) - known:
        return u"That group cannot be changed here."
    # 3. an administrator's account is changed by a Site Administrator
    #    (a Manager counts as one); roles that come through a group count
    if target_roles.intersection(PROTECTED_ROLES) and not \
            actor_roles.intersection(PROTECTED_ROLES):
        return u"A Site Administrator's account is changed by a Site Administrator."
    # 3b. the Lab Manager role is taken away only by a Site Administrator, so
    #     one Lab Manager cannot demote another and then take the account over
    if "LabManagers" in set(remove or ()) and not actor_roles.intersection(PROTECTED_ROLES):
        return u"Only a Site Administrator takes the Lab Manager role away."
    # 4. nobody changes their own roles
    if actor_id == target_id:
        return u"Nobody changes their own roles."
    # 5. every change carries a reason
    if not (reason or u"").strip():
        return u"Give a reason for the change."
    return None


def _effective_roles(portal, user_id):
    user = portal.acl_users.getUserById(user_id)
    if user is None:
        return None
    return list(user.getRolesInContext(portal))


def held_groups(portal, user_id):
    """The ROLE_GROUPS group ids the account holds: by membership, or by the
    group's role assigned to it directly."""
    user = portal.acl_users.getUserById(user_id)
    if user is None:
        return []
    member = set(portal.portal_groups.getGroupsForPrincipal(user))
    direct = set(portal.acl_users.portal_role_manager.getRolesForPrincipal(user))
    return [g for g, r, _l in ROLE_GROUPS if g in member or r in direct]


def apply(portal, actor_id, target_id, add, remove, reason):
    """Check, record, then change groups. Returns the refusal text or None.
    The actor is the current user of the security manager; a caller's
    actor_id that differs from it is refused."""
    from AccessControl.SecurityManagement import getSecurityManager
    from senaite.pfas import config_history

    actor = getSecurityManager().getUser()
    if actor is None or not actor.getId() or actor.getId() != actor_id:
        return u"Only a Lab Manager changes roles."
    actor_roles = list(actor.getRolesInContext(portal))
    target = portal.acl_users.getUserById(target_id)
    if target is None:
        return u"That person was not found."
    tid = target.getId()
    add, remove = set(add or ()), set(remove or ())
    refusal = check(actor.getId(), actor_roles, tid,
                    list(target.getRolesInContext(portal)), add, remove, reason)
    if refusal:
        return refusal
    # a group is either added or removed, never both
    if add & remove:
        return u"A group cannot be added and removed at once."
    # a group that itself carries an administrator role is never added here
    for gid in add:
        group = portal.portal_groups.getGroupById(gid)
        if group is None:
            return u"That group cannot be changed here."
        if set(group.getRoles()).intersection(PROTECTED_ROLES):
            return u"That group carries an administrator role."

    groups_tool = portal.portal_groups
    roles_tool = portal.acl_users.portal_role_manager
    role_ids = set(r for _g, r, _l in ROLE_GROUPS)
    group_ids = set(g for g, _r, _l in ROLE_GROUPS)

    def _held():
        user = portal.acl_users.getUserById(tid)
        return {
            "groups": sorted(set(groups_tool.getGroupsForPrincipal(user)) & group_ids),
            "direct": sorted(set(roles_tool.getRolesForPrincipal(user)) & role_ids),
            "roles": sorted(set(user.getRolesInContext(portal)) & role_ids),
        }

    # a strict store: if the entry cannot be prepared this raises, and no
    # group call has been made
    config_history.track(portal, "person_roles", tid, _held,
                         label=u"Roles", action=u"change roles", reason=reason)

    role_of = dict((g, r) for g, r, _l in ROLE_GROUPS)
    with _elevated(portal):
        for gid in sorted(add):
            groups_tool.addPrincipalToGroup(tid, gid)
        for gid in sorted(remove):
            groups_tool.removePrincipalFromGroup(tid, gid)
            # the role is also assigned directly; removing one not held is ignored
            roles_tool.removeRoleFromPrincipal(role_of[gid], tid)
    return None


@contextlib.contextmanager
def _elevated(portal):
    """Run the body as a Manager, then put the caller's security manager back
    by identity, error or not: adopt_roles edits the current manager in place
    and leaves Manager on it after an error."""
    from AccessControl.SecurityManagement import (
        getSecurityManager, newSecurityManager, setSecurityManager)
    from AccessControl.User import UnrestrictedUser
    saved = getSecurityManager()
    newSecurityManager(None, UnrestrictedUser(
        "pfas-role-guard", "", ["Manager"], []).__of__(portal.acl_users))
    try:
        yield
    finally:
        setSecurityManager(saved)


def may_manage_account(portal, target_id):
    """The refusal text, or None when the current user may manage the target's
    account (e-mail, password reset, contact): a Lab Manager or an administrator;
    an administrator's or another Lab Manager's account only by a Site
    Administrator; one's own account always."""
    from AccessControl.SecurityManagement import getSecurityManager
    actor = getSecurityManager().getUser()
    if actor is None or not actor.getId():
        return u"Only a Lab Manager manages accounts."
    actor_roles = set(actor.getRolesInContext(portal))
    if not actor_roles.intersection(_CHANGERS):
        return u"Only a Lab Manager manages accounts."
    target = portal.acl_users.getUserById(target_id)
    if target is None:
        return u"That person was not found."
    if target.getId() == actor.getId():
        return None
    target_roles = set(target.getRolesInContext(portal))
    is_admin = bool(actor_roles.intersection(PROTECTED_ROLES))
    if target_roles.intersection(PROTECTED_ROLES) and not is_admin:
        return u"A Site Administrator's account is changed by a Site Administrator."
    # one Lab Manager does not take over another's sign-in
    if "LabManager" in target_roles and not is_admin:
        return u"A Lab Manager's account is changed by a Site Administrator."
    return None


def send_reset(portal, target_id):
    """Mail the person a password reset link. Plone allows that only to a
    Manager, so the one call runs under the elevation, after the checks;
    the history entry is written once it has been sent. Returns the refusal
    text or None."""
    from senaite.pfas import config_history
    refusal = may_manage_account(portal, target_id)
    if refusal:
        return refusal
    target = portal.acl_users.getUserById(target_id)
    with _elevated(portal):
        portal.portal_registration.mailPassword(target.getId(), getattr(portal, "REQUEST", None))
    config_history.append(portal, {
        "store": "person_account", "key": target.getId(), "who": config_history.actor(),
        "label": u"Account of {0}".format(target.getId()),
        "action": u"reset e-mail sent", "changes": []})
    _log_reset(target.getId(), config_history.actor())
    return None


def _log_reset(userid, by):
    """A reset mailed opens a reset for review and tells the person
    (password_events.reset_mailed), once its transaction commits."""
    import logging
    try:
        from senaite.pfas import after_commit, password_events
        from senaite.pfas.esig import signing
        after_commit.run_once("reset-sent:%s" % userid, password_events.reset_mailed,
                              userid, signing.stamp(), by)
    except Exception:                                       # noqa: BLE001
        logging.getLogger("senaite.pfas.role_guard").warning(
            "reset e-mail of %s not kept with the signing events", userid, exc_info=True)
