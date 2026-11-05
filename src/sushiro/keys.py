"""Signing material, loaded at runtime instead of baked into the source.

The mini-program signs its own requests with a fixed HMAC key and encrypts
``X-App-Code`` with a fixed AES key. Both live inside the mini-program package,
so neither is a server-side secret — but shipping them in a public repository
would republish somebody else's extracted material. They are therefore read
from the environment or ``config.json``, and never committed.

    export SUSHIRO_SIGN_KEY=... SUSHIRO_AES_KEY=... SUSHIRO_AES_IV=...

    // config.json
    { "sign_key": "...", "aes_key": "...", "aes_iv": "..." }

``sign_key`` is required by the signed endpoints (``cities``). ``aes_key`` and
``aes_iv`` are only needed by ``login``, which mints ``X-App-Code``.
"""
from __future__ import annotations

import os

ENV = {
    "sign_key": "SUSHIRO_SIGN_KEY",
    "aes_key": "SUSHIRO_AES_KEY",
    "aes_iv": "SUSHIRO_AES_IV",
}

_cache: dict[str, str] = {}


class MissingKey(RuntimeError):
    """Raised when a call needs signing material the user has not provided."""


def _lookup(field: str) -> str:
    if field in _cache:
        return _cache[field]
    value = os.environ.get(ENV[field], "").strip()
    if not value:
        # Imported here so that importing this module never touches the
        # filesystem; the config path is only resolved when a key is needed.
        from . import auth
        value = str(auth.load_config().get(field) or "").strip()
    _cache[field] = value
    return value


def sign_key() -> bytes:
    value = _lookup("sign_key")
    if not value:
        raise MissingKey(
            "缺少 sign_key，签名请求需要它。设置环境变量 SUSHIRO_SIGN_KEY，或写进 "
            'config.json 的 "sign_key"。取值来自寿司郎小程序包 app-service.js 的 HMAC 密钥。'
        )
    return value.encode()


def aes() -> tuple[bytes, bytes]:
    key = _lookup("aes_key")
    iv = _lookup("aes_iv")
    if not key or not iv:
        raise MissingKey(
            "缺少 aes_key / aes_iv，只有 login（生成 X-App-Code）需要它们。设置环境变量 "
            'SUSHIRO_AES_KEY、SUSHIRO_AES_IV，或写进 config.json 的 "aes_key"/"aes_iv"。'
        )
    return key.encode(), iv.encode()


def status() -> dict[str, bool]:
    """Which fields are available right now — used by ``sushiro config``."""
    return {field: bool(_lookup(field)) for field in ENV}


def reset() -> None:
    """Drop cached values; only useful for tests that rewrite ``config.json``."""
    _cache.clear()
