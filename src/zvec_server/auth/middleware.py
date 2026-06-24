"""ASGI middleware that enforces an :class:`AuthProvider` on every request.

The liveness/readiness probes are exempt so orchestrators (Docker, Kubernetes)
can keep polling them without credentials. The middleware is only mounted when
authentication is enabled, so the default (disabled) configuration carries zero
overhead.

It is a plain ASGI middleware (rather than a ``BaseHTTPMiddleware``) so that it
sits *outside* the routing layer yet still renders failures with the project's
standard error envelope and a ``WWW-Authenticate`` header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from zvec_server.errors import AuthenticationError, build_error_payload

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from zvec_server.auth.provider import AuthProvider

#: Paths that never require authentication (liveness/readiness probes).
PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})


class AuthMiddleware:
    """Authenticate every HTTP request except the public health probes."""

    def __init__(
        self,
        app: ASGIApp,
        provider: AuthProvider,
        public_paths: frozenset[str] = PUBLIC_PATHS,
    ) -> None:
        self.app = app
        self.provider = provider
        self.public_paths = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.public_paths:
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization")
        try:
            self.provider.authenticate(authorization)
        except AuthenticationError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content=build_error_payload(exc.error_code, exc.message, exc.details),
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
