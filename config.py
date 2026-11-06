"""Runtime configuration: host, token, CA bundle, timeouts.

Rules that are enforced here and cannot be switched off:

* the host must be an ``https://`` URL (plain http is refused),
* TLS verification is always on — an internal CA is handled by pointing
  ``KADI_CA_BUNDLE`` to its PEM bundle, never by disabling verification,
* the token comes from the environment (``KADI_TOKEN``), never from files in the model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigError

DEFAULT_HOST = "https://kadi-test.vsb.cz"


@dataclass(frozen=True)
class Config:
    host: str
    token: str | None
    ca_bundle: str | None
    timeout: float
    state_dir: Path
    report_dir: Path

    @property
    def host_slug(self) -> str:
        return urlparse(self.host).netloc.replace(":", "_")


def validate_host(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(
            f"KADI_URL must be an https:// URL (got {host!r}). Plain http:// endpoints are not allowed."
        )
    return host


def load_dotenv_file(path: str | Path = ".env") -> list[str]:
    """Load KEY=VALUE pairs from a .env file into the environment (existing values win).

    Keeps the token out of the shell history and out of VS Code settings; the file itself
    is git-ignored. Only the variables of this tool are read (KADI_*)."""
    path = Path(path)
    loaded = []
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith("KADI_") and key not in os.environ and value:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def load_config(host: str | None = None, require_token: bool = True,
                state_dir: str | None = None, report_dir: str | None = None) -> Config:
    load_dotenv_file(os.environ.get("KADI_ENV_FILE", ".env"))
    host = validate_host(host or os.environ.get("KADI_URL") or DEFAULT_HOST)
    token = os.environ.get("KADI_TOKEN") or None
    if require_token and not token:
        raise ConfigError(
            "KADI_TOKEN is not set. Put it in your shell environment or in the .env file"
            " (never in the model or in Git)."
        )
    if token and token.strip().upper() == "TOKEN":
        raise ConfigError(
            "KADI_TOKEN still contains the placeholder TOKEN - replace it in .env with your personal"
            " access token from Kadi4Mat (Settings > Access tokens)."
        )
    ca_bundle = os.environ.get("KADI_CA_BUNDLE") or None
    if ca_bundle:
        if not Path(ca_bundle).is_file():
            raise ConfigError(f"KADI_CA_BUNDLE points to a missing file: {ca_bundle}")
    try:
        timeout = float(os.environ.get("KADI_TIMEOUT", "120"))
    except ValueError as exc:
        raise ConfigError("KADI_TIMEOUT must be a number of seconds") from exc
    return Config(
        host=host,
        token=token,
        ca_bundle=ca_bundle,
        timeout=timeout,
        state_dir=Path(state_dir or os.environ.get("KADI_STATE_DIR") or "state"),
        report_dir=Path(report_dir or os.environ.get("KADI_REPORT_DIR") or "reports"),
    )
