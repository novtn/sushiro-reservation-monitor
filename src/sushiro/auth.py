"""Config and token handling shared by the CLI and the capture addon."""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta

from . import paths

TOKEN_ENV = "SUSHIRO_TOKEN"
FRESH_MARGIN = timedelta(seconds=120)


def load_config() -> dict:
    target = paths.config()
    if not target.is_file():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(cfg: dict) -> None:
    paths.config().write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def token_expiry(token: str) -> datetime | None:
    """Decode the ``exp`` claim without verifying the signature.

    Verification needs the server's key, which never leaves the server; we only
    need to fail fast instead of sending a token we know is dead.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return datetime.fromtimestamp(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def is_fresh(token: str, *, margin: timedelta = FRESH_MARGIN,
             now: datetime | None = None) -> bool:
    expiry = token_expiry(token)
    if expiry is None:
        return False
    return expiry - margin > (now or datetime.now())


def read_token(cfg: dict | None = None) -> str:
    """Prefer the environment, then config.json, then a standalone token file."""
    env = os.environ.get(TOKEN_ENV)
    if env:
        return env.strip()
    cfg = cfg if cfg is not None else load_config()
    token = (cfg.get("auth_token") or "").strip()
    if token:
        return token
    target = paths.token_file()
    if target.is_file():
        return target.read_text(encoding="utf-8").strip()
    return ""


def store_token(token: str) -> None:
    paths.token_file().write_text(token + "\n", encoding="utf-8")
    cfg = load_config()
    cfg["auth_token"] = token
    save_config(cfg)
