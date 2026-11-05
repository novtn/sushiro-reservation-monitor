"""Request signing for the ``/api/3.0/*`` namespace.

Two independent mechanisms guard those endpoints:

* ``sign``  — HMAC-SHA256 over all query parameters sorted by name, prefixed
  with the nonce and timestamp that travel alongside it.
* ``X-App-Code`` — a daily rotating blob, AES-256-CBC encrypted and base64
  encoded. The plaintext embeds today's date, so a code minted yesterday is
  rejected and the value cannot be cached across midnight.

The key material behind both is read at runtime from :mod:`sushiro.keys`, never
compiled into this file. The gateway namespace (``/gateway/wechat/...``) uses
neither mechanism and only needs the bearer token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
import time
from datetime import datetime

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import keys

_NONCE_ALPHABET = string.ascii_letters + string.digits


def nonce(length: int = 6) -> str:
    return "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(length))


def signed_params(params: dict | None = None, *, now: int | None = None,
                  nonce_value: str | None = None) -> dict:
    """Return ``params`` plus ``ts``, ``nonce`` and ``sign``.

    The signature covers the business parameters too, so it must be computed
    after they are final. Sorting is by key name, and the HMAC input is
    ``k=v`` pairs joined by ``&`` with no URL encoding applied.
    """
    values = {
        "ts": int(now if now is not None else time.time()),
        "nonce": nonce_value or nonce(),
        **(params or {}),
    }
    message = "&".join(f"{name}={values[name]}" for name in sorted(values))
    values["sign"] = hmac.new(keys.sign_key(), message.encode(), hashlib.sha256).hexdigest()
    return values


def app_code(now: datetime | None = None) -> str:
    """Build today's ``X-App-Code``.

    The plaintext is ``{12345678-y+m-d}QWERlkjhVb-{y}-{m}-{d}`` evaluated as
    arithmetic in the first brace pair, which is what the mini-program ships.
    """
    moment = now or datetime.now()
    plaintext = (
        f"{12345678 - moment.year + moment.month - moment.day}"
        f"QWERlkjhVb-{moment.year}-{moment.month}-{moment.day}"
    )
    aes_key, aes_iv = keys.aes()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_iv)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()
