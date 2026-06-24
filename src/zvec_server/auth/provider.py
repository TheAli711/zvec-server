"""Authentication providers — a small, pluggable strategy abstraction.

V1 ships two providers:

* :class:`DisabledAuthProvider` — authentication is off; every request passes.
* :class:`ApiKeyAuthProvider` — requires ``Authorization: Bearer <api_key>`` and
  compares the presented key against a single configured secret in constant time.

The abstraction exists so that richer schemes (multiple keys, JWT, mTLS, an
external identity provider) can be added later by writing a new
:class:`AuthProvider` and wiring it into :func:`build_auth_provider`, without
touching routing or business logic. A provider only inspects the raw
``Authorization`` header value, so it stays decoupled from the HTTP framework and
is trivial to unit-test.
"""

from __future__ import annotations

import hmac
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from zvec_server.errors import AuthenticationError

if TYPE_CHECKING:
    from zvec_server.config import Settings

_BEARER_SCHEME = "bearer"


class AuthProvider(ABC):
    """Strategy that decides whether a request is authenticated."""

    #: Whether this provider enforces any credentials. When ``False`` the
    #: middleware is not even mounted, so authentication adds zero overhead.
    enabled: bool = True

    @abstractmethod
    def authenticate(self, authorization: str | None) -> None:
        """Validate the raw ``Authorization`` header value.

        Args:
            authorization: The verbatim ``Authorization`` header, or ``None`` if
                the client did not send one.

        Raises:
            AuthenticationError: If credentials are missing or invalid (``401``).
        """


class DisabledAuthProvider(AuthProvider):
    """No-op provider used when authentication is disabled."""

    enabled = False

    def authenticate(self, authorization: str | None) -> None:
        return None


class ApiKeyAuthProvider(AuthProvider):
    """Compare a bearer token against a single configured API key.

    The comparison uses :func:`hmac.compare_digest` so it runs in constant time
    and does not leak the key length or contents via timing side channels.
    """

    enabled = True

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._expected = api_key.encode("utf-8")

    def authenticate(self, authorization: str | None) -> None:
        if not authorization:
            raise AuthenticationError("Missing Authorization header.")
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() != _BEARER_SCHEME or not token:
            raise AuthenticationError("Invalid Authorization header; expected 'Bearer <api_key>'.")
        if not hmac.compare_digest(token.encode("utf-8"), self._expected):
            raise AuthenticationError("Invalid API key.")


def build_auth_provider(settings: Settings) -> AuthProvider:
    """Select an :class:`AuthProvider` from configuration.

    Returns a :class:`DisabledAuthProvider` when ``auth_enabled`` is false,
    otherwise an :class:`ApiKeyAuthProvider`. ``Settings`` validation guarantees
    a key is present when auth is enabled; the check here is defensive.
    """
    if not settings.auth_enabled:
        return DisabledAuthProvider()
    if not settings.api_key:
        raise ValueError("Authentication is enabled but ZVEC_SERVER_API_KEY is not set.")
    return ApiKeyAuthProvider(settings.api_key.get_secret_value())
