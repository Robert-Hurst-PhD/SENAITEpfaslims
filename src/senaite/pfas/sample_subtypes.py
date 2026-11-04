# -*- coding: utf-8 -*-
"""Sample sub-types: a core Sample Type lists the
sub-types its samples may be (Meat / Muscle: Beef, Pork ...). A CoC sample
of the type picks one; a regulatory limit that names sub-types applies only
to samples of those sub-types. Sub-types carry limits only: a sub-type uses
the method profile's settings for its type.

    subtypes = [{"id", "name", "off": [method ids]}]

`id` is a stable slug made once from the name (limits and samples name the
id, so a rename orphans nothing); `off` lists the method profiles that
analyse the type but not this sub-type (which profiles analyse a type is
their matrices'). A sub-type a limit or a sample names is not removed.

    from_form(form, old, profile_ids, named) -> (subtypes, [error])
    offered(subtypes, method_id)  -> [(id, name)]
    profiles_for(type_uid, type_title, profiles) -> [method id]
    name_of(subtypes, id) / slug(name, taken)
    load(sample_type) / save(sample_type, subtypes)

Pure helpers; the annotation shell imports Zope lazily. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

KEY = "senaite.pfas.sampletype.subtypes"


def slug(name, taken):
    base = re.sub(r"[^a-z0-9]+", u"-", (name or u"").lower().replace(u"'", u"")).strip(u"-") or u"subtype"
    out, n = base, 1
    while out in (taken or []):
        n += 1
        out = u"%s-%d" % (base, n)
    return out


def _t(form, key):
    return (u"%s" % (form.get(key) or u"")).strip()


def _plural(n, word):
    return u"%d %s%s" % (n, word, u"" if n == 1 else u"s")


def from_form(form, old, profile_ids, named):
    """(subtypes, errors) from the dialog's rows st.<i>.{id, name, remove,
    on.<method id>}. `named`: {id: {"limits", "samples"}} -- a sub-type
    something names stays when Remove is asked."""
    form = form or {}
    old_by = dict((s["id"], s) for s in old or [])
    idx = sorted(set(int(k.split(u".")[1]) for k in form if k.startswith(u"st.") and k.split(u".")[1].isdigit()))
    # an existing sub-type the dialog no longer posts was removed there
    posted = set(_t(form, u"st.%d.id" % i) for i in idx)
    for sid in [x for x in old_by if x not in posted]:
        i = (max(idx) + 1) if idx else 0
        form = dict(form, **{u"st.%d.id" % i: sid, u"st.%d.remove" % i: u"on"})
        idx.append(i)
    out, errors, seen = [], [], set()
    taken = list(old_by)
    for i in idx:
        sid, name = _t(form, u"st.%d.id" % i), _t(form, u"st.%d.name" % i)
        prev = old_by.get(sid)
        if form.get(u"st.%d.remove" % i) and prev is not None:
            n = named.get(sid) or {}
            if n.get("limits") or n.get("samples"):
                errors.append(u"%s is named by %s and %s: it stays." % (
                    prev["name"], _plural(n.get("limits") or 0, u"limit"), _plural(n.get("samples") or 0, u"sample")))
                out.append(prev)
            continue
        if not name:
            if prev is not None:
                out.append(prev)        # a cleared name keeps the sub-type as it was
            continue
        if name.lower() in seen:
            errors.append(u"%s is listed twice." % name)
            continue
        seen.add(name.lower())
        if prev is None:
            sid = slug(name, taken)
            taken.append(sid)
        off = [m for m in profile_ids or [] if not form.get(u"st.%d.on.%s" % (i, m))]
        out.append({"id": sid, "name": name, "off": off})
    return out, errors


def profiles_for(type_uid, type_title, profiles):
    """The method profiles that analyse a Sample Type: those whose matrices
    name it (by its UID, else its title). `profiles`: {method id: profile}."""
    out = []
    for mid in sorted(profiles or {}):
        p = profiles[mid] or {}
        if type_uid in ((p.get("matrix_uid_map") or {}).values()) or type_title in (p.get("supported_matrices") or []):
            out.append(mid)
    return out


def offered(subtypes, method_id):
    return [(s["id"], s["name"]) for s in subtypes or [] if method_id not in (s.get("off") or [])]


def name_of(subtypes, sid):
    return dict((s["id"], s["name"]) for s in subtypes or []).get(sid, sid)


# ── storage (Zope) ───────────────────────────────────────────────────────────

def load(sample_type):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(sample_type).get(KEY) or "[]")
    except (TypeError, ValueError):
        return []


def save(sample_type, subtypes):
    from zope.annotation.interfaces import IAnnotations
    from bika.lims import api
    from senaite.pfas import config_history
    config_history.track(None, "sample_subtypes", sample_type.UID(), lambda: load(sample_type),
                         label=u"Sub-types of %s" % api.safe_unicode(api.get_title(sample_type)))
    IAnnotations(sample_type)[KEY] = json.dumps(subtypes, sort_keys=True)
