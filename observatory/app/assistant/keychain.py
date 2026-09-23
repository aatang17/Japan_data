"""Where a desk's secrets sleep: the customer's model key and Slack webhook.

Sealed with a key derived from `ASSISTANT_SECRET`, a long random string set on
the deployment and nowhere else. Without it the store refuses to hold a secret
at all — a desk can still be browsed, but no run can start, and the settings
page says why.

The construction is the standard library's, because the app carries no crypto
dependency and must not gain one for this: a per-item random nonce, a
keystream drawn from HMAC-SHA256 in counter mode, and an HMAC-SHA256 tag over
nonce and ciphertext checked before anything is decrypted. It keeps a key out
of a copied database and detects tampering. It is not a substitute for a
managed secret store, and the plan's M0 ("keys stored hashed / encrypted;
revocable from the admin console") should move to one when the product does.
"""
import base64
import hashlib
import hmac
import os
import secrets

_TAG_LEN = 32
_NONCE_LEN = 16


def enabled():
    return bool((os.environ.get("ASSISTANT_SECRET") or "").strip())


def _master():
    secret = (os.environ.get("ASSISTANT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("ASSISTANT_SECRET is not set, so secrets cannot be stored.")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _keystream(key, nonce, length):
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def seal(plaintext):
    """Encrypt and authenticate a string. Returns a base64 token."""
    key = _master()
    nonce = secrets.token_bytes(_NONCE_LEN)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, nonce, len(data))
    ct = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + ct + tag).decode("ascii")


def open_(token):
    """Decrypt a token produced by seal(); raises ValueError if it was altered."""
    key = _master()
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(raw) < _NONCE_LEN + _TAG_LEN:
        raise ValueError("sealed value is too short")
    nonce, ct, tag = raw[:_NONCE_LEN], raw[_NONCE_LEN:-_TAG_LEN], raw[-_TAG_LEN:]
    expect = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expect):
        raise ValueError("sealed value failed authentication")
    stream = _keystream(key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, stream)).decode("utf-8")


def last4(value):
    value = (value or "").strip()
    return value[-4:] if len(value) >= 4 else ""
