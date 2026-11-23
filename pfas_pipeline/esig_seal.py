"""The lab's records seal: the worker's fourth thread, and the one module
that touches the signing library (pyHanko), so a swap of it stays here.

The worker alone holds the seal key (a PKCS#12 and its passphrase, Docker
secrets). With it:

- every finished PDF is sealed once, as its very last write: an invisible
  PAdES B-B signature added as an incremental update, so the bytes before
  it are the PDF as built and any later rewrite of the file breaks it
  (seal_pdf; verify_pdf reads it back);
- every signature-ledger row is sealed with a detached CMS signature over
  the chain text it was hashed from and the time of its seal,
  prev + "\\n" + entry + "\\n" + sealed_at (row_text; sign_text,
  verify_text), so the seal time is part of what the seal certifies; the
  signing thread fills each row's seal columns once (seal_rows) and keeps
  the seal certificate beside the ledger as
  <certs dir>/<sha256 fingerprint>.pem.

Each tick the signing thread rewrites <ledger dir>/signatures.head, JSON
{"at", "seq", "hash", "key_ok", "cert_not_before", "cert_not_after"}: the
ledger's last row as the worker last saw it, whether the key can seal
now, and the seal certificate's validity (null without a key). Beside it,
<ledger dir>/signatures.head.sig, JSON {"cert", "seal"}: a detached seal by
the same key over the head file's exact text, so a head written by anyone
but the worker is told apart; with no usable key the old one is removed,
never left over a head it does not seal.

A missing, empty or unreadable key fails closed and is visible, never
blocking lab work: load_signer answers None and logs "Seal key
unavailable"; rows stay unsealed; a PDF to be sealed raises
SealUnavailable. A key whose
certificate has expired or is not yet valid seals nothing either, the same
way, with the reason "Seal certificate expired" or "Seal certificate not
yet valid" (unusable). Python 3.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

log = logging.getLogger("pfas_pipeline.esig_seal")

UNAVAILABLE = "Seal key unavailable"
EXPIRED = "Seal certificate expired"
NOT_YET_VALID = "Seal certificate not yet valid"
FIELD = "RecordsSeal"
GENESIS = "0" * 64
HEAD_NAME = "signatures.head"
HEAD_SIG_NAME = "signatures.head.sig"
SEALED_AT = "%Y-%m-%dT%H:%M:%SZ"
DIR_MODE = 0o770
DEFAULT_P12 = "/run/secrets/pfas_seal_p12"
DEFAULT_PASS = "/run/secrets/pfas_seal_pass"


class SealUnavailable(Exception):
    """There is no seal key to seal with."""

    def __init__(self, message=UNAVAILABLE):
        super().__init__(message)


# ── the key ──────────────────────────────────────────────────────────────────

NO_KEY = "no key installed"


def load_signer(p12_path, pass_path):
    """The seal signer from the PKCS#12 and its passphrase file, or None
    when either cannot be read, or is empty: the placeholders a checkout
    starts with before the lab has a key (logged as "Seal key
    unavailable")."""
    try:
        from pyhanko.sign import signers
    except ImportError as exc:
        log.warning("%s: the signing library is not installed (%s)", UNAVAILABLE, exc)
        return None
    try:
        with open(pass_path, "rb") as fh:
            passphrase = fh.read().strip()
        with open(p12_path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        log.warning("%s: %s", UNAVAILABLE, exc)
        return None
    if not data.strip() or not passphrase:
        log.warning("%s: %s", UNAVAILABLE, NO_KEY)
        return None
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(data, other_certs=[], passphrase=passphrase)
    except Exception as exc:                                # noqa: BLE001
        log.warning("%s: the key cannot be opened (%s)", UNAVAILABLE, type(exc).__name__)
        return None
    if signer is None:
        log.warning("%s: the key cannot be opened", UNAVAILABLE)
    return signer


def signer_from_env(env=None):
    """The seal signer from the secrets the environment names."""
    env = os.environ if env is None else env
    return load_signer(env.get("PFAS_SEAL_P12") or DEFAULT_P12, env.get("PFAS_SEAL_PASS") or DEFAULT_PASS)


def _utcnow():
    return datetime.now(timezone.utc)


def cert_window(signer):
    """(not before, not after) of the seal certificate, UTC datetimes."""
    cert = signer.signing_cert
    return cert.not_valid_before, cert.not_valid_after


def unusable(signer, now=_utcnow):
    """Why the signer may not seal now, or None: no key, or a certificate
    expired or not yet valid. A seal is made only inside its
    certificate's validity, so a verifier never meets one made outside
    it."""
    if signer is None:
        return UNAVAILABLE
    start, end = cert_window(signer)
    at = now()
    if at > end:
        return EXPIRED
    if at < start:
        return NOT_YET_VALID
    return None


def require(signer, now=None):
    """SealUnavailable with the reason when the signer may not seal now
    (`now`, the clock a caller judges by; the real one when not given)."""
    why = unusable(signer, now or _utcnow)
    if why:
        raise SealUnavailable(why)


def _require(signer, now=None):
    require(signer, now)


def cert_fp(signer):
    """The sha256 fingerprint (hex) of the seal certificate's DER: the name
    the ledger, the stored records and the certificate file know it by."""
    if signer is None:
        raise SealUnavailable()
    return hashlib.sha256(signer.signing_cert.dump()).hexdigest()


def cert_pem(signer):
    from asn1crypto import pem
    return pem.armor("CERTIFICATE", signer.signing_cert.dump())


# ── sealing a PDF ────────────────────────────────────────────────────────────

def seal_name(lab_name):
    """The seal's /Name: the lab's records seal."""
    lab = (lab_name or "").strip()
    return f"{lab} records seal" if lab else "Laboratory records seal"


def seal_reason(report_id, revision):
    return f"sealed · {report_id} revision {revision}"


def seal_pdf(pdf_bytes, signer, name, reason):
    """The PDF sealed: an invisible PAdES B-B signature appended as an
    incremental update; nothing before it changes."""
    _require(signer)
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    meta = signers.PdfSignatureMetadata(field_name=FIELD, name=name, reason=reason,
                                        subfilter=fields.SigSeedSubFilter.PADES, md_algorithm="sha256")
    out = io.BytesIO()
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    signers.PdfSigner(meta, signer=signer).sign_pdf(writer, output=out)
    return out.getvalue()


def _certs(pem_bytes):
    from asn1crypto import pem, x509
    out = []
    for _kind, _headers, der in pem.unarmor(pem_bytes, multiple=True):
        out.append(x509.Certificate.load(der))
    return out


def verify_pdf(pdf_bytes, ca_pem=None):
    """The PDF's last signature checked against the lab CA: valid (intact,
    the signature good and the chain trusted), intact (the signed bytes
    unchanged), signature_ok (the signature over them is the key's own),
    trusted (the chain ends at the CA), coverage (the signature coverage's
    name, ENTIRE_FILE when nothing follows the seal; None when the PDF holds
    no signature), error (why the PDF or its seal could not be read, else
    None). Without ca_pem the seal is checked for its integrity, signature
    and coverage alone, against no trust root (never the system's): trusted
    and valid are then always False. The chain is judged at the seal's
    own signing time, so a seal outlives its certificate; with no
    timestamp authority that time is the sealer's own claim. A seal that
    states no signing time is judged now."""
    out = {"valid": False, "intact": False, "signature_ok": False, "trusted": False,
           "coverage": None, "error": None}
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
        sigs = PdfFileReader(io.BytesIO(pdf_bytes), strict=False).embedded_signatures
        if not sigs:
            return out
        roots = _certs(ca_pem) if ca_pem is not None else []
        at = sigs[-1].self_reported_timestamp
        status = validate_pdf_signature(sigs[-1], ValidationContext(trust_roots=roots, moment=at))
    except Exception as exc:                                # noqa: BLE001
        log.info("seal check: %s", exc)
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    out.update(valid=bool(status.bottom_line), intact=bool(status.intact),
               signature_ok=bool(status.valid), trusted=bool(status.trusted),
               coverage=status.coverage.name if status.coverage is not None else None)
    return out


# ── sealing a ledger row ─────────────────────────────────────────────────────

def sign_text(text, signer, now=None):
    """(the detached CMS over the text's UTF-8, base64; the seal
    certificate's fingerprint); refused outside the certificate's validity
    by `now` (the real clock when not given)."""
    _require(signer, now)
    cms = asyncio.run(signer.async_sign_general_data(text.encode("utf-8"), "sha256", detached=True))
    return base64.b64encode(cms.dump()).decode("ascii"), cert_fp(signer)


def within(cert_pem_bytes, at):
    """True when `at` (an aware datetime) lies inside the validity of the
    first certificate of the PEM given; False when it cannot be read."""
    try:
        validity = _certs(cert_pem_bytes)[0]["tbs_certificate"]["validity"]
        return validity["not_before"].native <= at <= validity["not_after"].native
    except Exception as exc:                                # noqa: BLE001
        log.info("seal certificate validity: %s", exc)
        return False


def verify_text(text, seal_b64, cert_pem_bytes, at=None):
    """True when seal_b64 is a detached signature over the text, intact,
    made by the key of the certificate given; with `at` (when the seal was
    made, an aware datetime), only when the certificate was valid then: a
    seal outlives its certificate, but none is made outside it."""
    if at is not None and not within(cert_pem_bytes, at):
        return False
    try:
        from asn1crypto import cms
        from pyhanko.sign.validation import async_validate_detached_cms
        from pyhanko_certvalidator import ValidationContext
        expected = _certs(cert_pem_bytes)
        info = cms.ContentInfo.load(base64.b64decode(seal_b64, validate=True))
        signed = info["content"]
        found = [c.chosen for c in signed["certificates"]]
        if not expected or expected[0].dump() not in [c.dump() for c in found]:
            return False
        status = asyncio.run(async_validate_detached_cms(
            text.encode("utf-8"), signed,
            signer_validation_context=ValidationContext(trust_roots=expected, moment=at)))
    except Exception as exc:                                # noqa: BLE001
        log.info("ledger seal check: %s", exc)
        return False
    return bool(status.intact and status.valid and status.signing_cert.dump() == expected[0].dump())


# ── the ledger ───────────────────────────────────────────────────────────────

def _stamp(now):
    return now.astimezone(timezone.utc).strftime(SEALED_AT)


def _open(db_path):
    """The ledger opened for reading and sealing, or None when it is not
    made yet: the worker never makes it, the add-on does at its first
    signature."""
    if not os.path.isfile(db_path):
        return None
    return sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=30, isolation_level=None)


def row_text(prev, entry, sealed_at):
    """What a ledger row's seal is made over: its chain text and the time
    of the seal, prev + newline + entry + newline + sealed_at. The worker
    seals it and the verifier checks it by this one rule."""
    return prev + "\n" + entry + "\n" + sealed_at


def _chain_hash(prev, entry):
    return hashlib.sha256((prev + "\n" + entry).encode("utf-8")).hexdigest()


def keep_cert(signer, certs_dir):
    """The seal certificate kept as <certs_dir>/<fingerprint>.pem, written
    once; its path."""
    fp = cert_fp(signer)
    path = os.path.join(certs_dir, fp + ".pem")
    if os.path.isfile(path):
        return path
    if not os.path.isdir(certs_dir):
        os.makedirs(certs_dir, exist_ok=True)
        os.chmod(certs_dir, DIR_MODE)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(cert_pem(signer))
    os.replace(tmp, path)
    return path


def seal_rows(db_path, signer, certs_dir, now=_utcnow):
    """Seal every unsealed ledger row whose hash is of its own prev and
    entry, oldest first; the count sealed. A row whose hash does not match
    is left unsealed and logged: a seal never certifies a changed row. The
    seal columns fill once (the ledger's triggers refuse a second fill)."""
    _require(signer, now)
    conn = _open(db_path)
    if conn is None:
        return 0
    sealed = 0
    try:
        rows = conn.execute("SELECT seq, prev, entry, hash FROM signatures "
                            "WHERE seal IS NULL ORDER BY seq").fetchall()
        if rows:
            keep_cert(signer, certs_dir)
        for seq, prev, entry, digest in rows:
            if _chain_hash(prev, entry) != digest:
                log.error("signature row %s is not sealed: its hash is not of its own content", seq)
                continue
            at = _stamp(now())
            seal_b64, fp = sign_text(row_text(prev, entry, at), signer, now)
            cur = conn.execute("UPDATE signatures SET seal=?, seal_cert=?, sealed_at=? "
                               "WHERE seq=? AND seal IS NULL", (seal_b64, fp, at, seq))
            sealed += cur.rowcount
    finally:
        conn.close()
    if sealed:
        log.info("sealed %d signature row(s)", sealed)
    return sealed


def head(db_path):
    """(seq, hash) of the ledger's last row; (0, GENESIS) when it has none."""
    conn = _open(db_path)
    if conn is None:
        return 0, GENESIS
    try:
        r = conn.execute("SELECT seq, hash FROM signatures ORDER BY seq DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        r = None
    finally:
        conn.close()
    return (r[0], r[1]) if r else (0, GENESIS)


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_head(db_path, signer, now=_utcnow, certs_dir=None):
    """<ledger dir>/signatures.head rewritten whole: {"at", "seq", "hash",
    "key_ok", "cert_not_before", "cert_not_after"}; key_ok only when the
    signer may seal now. Then signatures.head.sig, {"cert", "seal"}: the
    head's text sealed by the same key (its certificate kept in certs_dir
    when given), or removed when the key may not seal."""
    seq, digest = head(db_path)
    path = os.path.join(os.path.dirname(db_path) or ".", HEAD_NAME)
    start, end = cert_window(signer) if signer is not None else (None, None)
    body = {"at": _stamp(now()), "seq": seq, "hash": digest, "key_ok": unusable(signer, now) is None,
            "cert_not_before": _stamp(start) if start else None,
            "cert_not_after": _stamp(end) if end else None}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    _write(path, text)
    sig_path = os.path.join(os.path.dirname(path), HEAD_SIG_NAME)
    sig = None
    if body["key_ok"]:
        try:
            if certs_dir:
                keep_cert(signer, certs_dir)
            seal_b64, fp = sign_text(text, signer, now)
            sig = json.dumps({"cert": fp, "seal": seal_b64}, sort_keys=True, separators=(",", ":"))
        except Exception:                                   # noqa: BLE001
            log.exception("the head file could not be sealed")
    if sig is not None:
        _write(sig_path, sig)
    elif os.path.isfile(sig_path):
        os.remove(sig_path)
    return body


def tick(db_path, signer_fn, certs_dir, after=None, now=_utcnow):
    """One poll: the key read (logged once when it cannot be, or when its
    certificate is out of date), the ledger's unsealed rows sealed, then
    `after(signer)` (the certificate seal queue, which fails its jobs with
    the same reason), then the head file. A failure of one step is logged
    and the next still runs; the head file is always written."""
    signer = signer_fn()
    why = unusable(signer, now)
    if signer is not None and why:
        log.warning(why)
    try:
        if why is None:
            seal_rows(db_path, signer, certs_dir, now)
    except Exception:                                       # noqa: BLE001
        log.exception("signature rows could not be sealed")
    if after is not None:
        try:
            after(signer)
        except Exception:                                   # noqa: BLE001
            log.exception("the certificate seal queue failed")
    return write_head(db_path, signer, now, certs_dir)


def loop(db_path, signer_fn, every, certs_dir, after=None):
    """The worker's signing thread: a poll every `every` seconds."""
    log.info("Signing queue %s (every %ss)", db_path, every)
    while True:
        try:
            tick(db_path, signer_fn, certs_dir, after)
        except Exception:                                   # noqa: BLE001
            log.exception("signing poll failed")
        time.sleep(every)
