"""The timed retry of certificate e-mails that waited: a thread of the
worker's own.

Every few minutes the worker posts SENAITE's own resend,
@@pfas-delivery-send with auto=1, the one a Manager presses on
Certificates: SENAITE sends again, through the e-mail form's send, every
current issue whose e-mail waits after an attempt, and answers JSON
{"ok", "mail", "sent": [sample id], "waiting": [sample id]}. While no
mail server is named SENAITE tries nothing ("mail": false) and records
nothing. The worker holds no mail logic of its own.

The wait between posts is `every` seconds while nothing fails; it doubles
after a post that left an e-mail waiting, or that SENAITE did not answer,
up to `most`, and is `every` again once nothing waits. Python 3.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("pfas_pipeline.delivery_retry")

VIEW = "@@pfas-delivery-send"
TIMEOUT = 300


class RetryFault(Exception):
    """SENAITE did not answer the retry as the view answers it."""


def post(session, base_url, timeout=TIMEOUT):
    """SENAITE's answer to one timed retry, a dict; RetryFault when it did
    not answer, or answered as if the worker were not signed in."""
    url = f"{base_url.rstrip('/')}/{VIEW}"
    try:
        resp = session.post(url, data={"auto": "1"}, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise RetryFault(f"{VIEW}: {exc}") from exc
    if resp.status_code != 200:
        raise RetryFault(f"{VIEW} answered HTTP {resp.status_code}: check the worker's SENAITE account")
    try:
        body = resp.json()
    except ValueError:
        raise RetryFault(f"{VIEW} answered a page, not JSON: check the worker's SENAITE account") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise RetryFault(f"{VIEW} did not confirm the retry")
    return body


def next_wait(body, wait, every, most):
    """The seconds until the next post: `every` while nothing failed (no
    mail server named, nothing waiting, or every e-mail sent), else the
    last wait doubled, never past `most`. `body` None is a post SENAITE
    did not answer."""
    if body is not None and (not body.get("mail") or not body.get("waiting")):
        return every
    return min(max(wait, every) * 2, most)


def tick(session, base_url):
    """One timed retry: SENAITE's answer, or None when it did not answer
    (logged)."""
    try:
        body = post(session, base_url)
    except RetryFault as exc:
        log.error("certificate e-mail retry: %s", exc)
        return None
    if body.get("sent") or body.get("waiting"):
        log.info("certificate e-mail retry: e-mailed %s; still waiting %s",
                 ", ".join(body.get("sent") or []) or "none", ", ".join(body.get("waiting") or []) or "none")
    return body


def loop(session, base_url, every, most, sleep=time.sleep):
    """The worker's retry thread: a post every `every` seconds, backing off
    to `most` while e-mails keep failing."""
    log.info("Certificate e-mail retry every %ss (backing off to %ss)", every, most)
    wait = every
    while True:
        sleep(wait)
        try:
            body = tick(session, base_url)
        except Exception:                                   # noqa: BLE001
            log.exception("certificate e-mail retry failed")
            body = None
        wait = next_wait(body, wait, every, most)
