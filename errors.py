"""Exception types used across the package."""
from __future__ import annotations


class KadiLabError(Exception):
    """Base class for all errors raised by Kadi Lab Manager."""


class ModelError(KadiLabError):
    """The YAML model is invalid (structure, references, vocabulary, values)."""

    def __init__(self, problems):
        self.problems = list(problems) if not isinstance(problems, str) else [problems]
        super().__init__("\n".join(f"- {p}" for p in self.problems))


class ConfigError(KadiLabError):
    """Missing or invalid runtime configuration (host, token, CA bundle)."""


class ApiError(KadiLabError):
    """The Kadi4Mat API answered with an unexpected status."""

    def __init__(self, method, endpoint, status, body):
        self.method, self.endpoint, self.status, self.body = method, endpoint, status, body
        super().__init__(f"HTTP {status} for {method.upper()} {endpoint}: {body}")


class StateError(KadiLabError):
    """The local state file is inconsistent with the request."""
