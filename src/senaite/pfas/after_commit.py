# -*- coding: utf-8 -*-
"""Files the worker reads are written after the transaction holding the save
has committed: a save that aborts, or that a strict store's history refuses,
never reaches them. One write per key per transaction, however many saves it
holds; a failed write is logged (the start-up export rewrites the files).

    run_once(key, fn, *args)    fn(*args) once this transaction commits
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.after_commit")


def run_once(key, fn, *args):
    """A later call with the same key replaces the earlier call's fn/args."""
    import transaction
    txn = transaction.get()
    for hook, hook_args, _kws in txn.getAfterCommitHooks():
        if hook is _run and hook_args[0] == key:
            hook_args[1][:] = [fn, args]
            return
    txn.addAfterCommitHook(_run, args=(key, [fn, args]))


def _run(ok, key, call):
    if not ok:
        return
    fn, args = call
    try:
        fn(*args)
    except Exception:                                       # noqa: BLE001
        logger.exception("%s: committed, but the file was not written", key)
