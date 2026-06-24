"""Authentication layer: a pluggable provider abstraction plus ASGI middleware.

Designed to keep V1 minimal (a single static API key) while leaving a clean seam
for future schemes. Routing and business logic never reference this package
directly; the middleware is wired in once in :mod:`zvec_server.app`.
"""

from zvec_server.auth.middleware import PUBLIC_PATHS, AuthMiddleware
from zvec_server.auth.provider import (
    ApiKeyAuthProvider,
    AuthProvider,
    DisabledAuthProvider,
    build_auth_provider,
)

__all__ = [
    "PUBLIC_PATHS",
    "ApiKeyAuthProvider",
    "AuthMiddleware",
    "AuthProvider",
    "DisabledAuthProvider",
    "build_auth_provider",
]
