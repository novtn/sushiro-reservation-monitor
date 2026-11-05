"""Where sushiro keeps its config, token, state and logs.

Resolution order, first hit wins:
  1. ``--data-dir`` passed on the command line
  2. ``$SUSHIRO_HOME``
  3. ``./config.json`` in the current directory (keeps in-repo development zero-config)
  4. ``~/.sushiro``

The skill is installed outside this repository, so anything that hardcodes the
repository root breaks there. Every path goes through this module instead.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "SUSHIRO_HOME"
_DEFAULT_DIR = ".sushiro"

_root: Path | None = None


def resolve(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the data root without permanently binding it."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    cwd_config = Path.cwd() / "config.json"
    if cwd_config.is_file():
        return Path.cwd()
    return (Path.home() / _DEFAULT_DIR).resolve()


def bind(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Fix the data root for this process and make sure it exists."""
    global _root
    _root = resolve(explicit)
    _root.mkdir(parents=True, exist_ok=True)
    return _root


def root() -> Path:
    if _root is None:
        return bind()
    return _root


def config() -> Path:
    return root() / "config.json"


def config_example() -> Path:
    return root() / "config.example.json"


def token_file() -> Path:
    return root() / "token.txt"


def state() -> Path:
    return root() / "state.json"


def snapshots() -> Path:
    return root() / "snapshots.jsonl"


def expired_flag() -> Path:
    return root() / "token-expired.flag"


def samples() -> Path:
    return root() / "samples"


def logs() -> Path:
    return root() / "logs"


def mitm_confdir() -> Path:
    return root() / ".mitmconf"


def mitm_log() -> Path:
    return root() / "mitm.log"
