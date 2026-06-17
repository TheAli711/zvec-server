---
id: SPEC-005
title: Optional API-key authentication
status: accepted
created: 2026-06-17
release: v0.1.0
---

# SPEC-005: Optional API-key authentication

## Summary

Add opt-in authentication with a single static API key. When
`ZVEC_SERVER_AUTH_ENABLED=true`, every HTTP request except the health probes must send
`Authorization: Bearer <api_key>`; anything else gets a 401 in the standard error
envelope. When disabled (the default) nothing changes and the check is not even
installed. The mechanism sits behind a small `AuthProvider` abstraction and a plain
ASGI middleware so routes and business logic never see it.

## Motivation

With SPEC-002 through SPEC-004 the server can create, write, search, and drop
collections, and every one of those routes is open to anyone who can reach the port.
Many deployments run the server on a shared network (a Docker network, a VPC, a
Kubernetes cluster) where "reachable" is not the same as "trusted". A shared-secret
check is the smallest thing that stops accidental or casual access, and it pairs with
how these deployments already manage secrets (env vars, Docker/Kubernetes secrets,
cloud secret managers). Anything richer would drag the server toward users and roles,
which the project's thin-storage-layer scope rules out.

## Goals

- Off by default; enabled and configured entirely through the environment.
- One static key, sent as a standard bearer token.
- Health probes stay public so orchestrators can poll without credentials.
- Failures use the same JSON error envelope as every other error, plus
  `WWW-Authenticate: Bearer`.
- Constant-time key comparison; the key never appears in logs, reprs, or tracebacks.
- A clean seam for other schemes later, without touching routers.
- Zero overhead when disabled.

## Non-goals

- Users, roles, scopes, sessions, JWT, OAuth, or mTLS inside the server.
- Multiple keys, per-key permissions, key rotation without restart, or revocation.
- Per-collection or per-operation authorization. A valid key grants full access.
- Rate limiting, quotas, or lockout after failed attempts.
- Storing keys or auth state in SQLite or on disk. The metadata store stays
  collection-only.
- TLS termination. The server speaks plain HTTP; TLS belongs to a proxy or gateway.
- Alternative credential locations (query string, custom header, cookie).

## Requirements

- **R1.** `Settings` must gain `auth_enabled: bool = False`
  (`ZVEC_SERVER_AUTH_ENABLED`) and `api_key: SecretStr | None = None`
  (`ZVEC_SERVER_API_KEY`).
- **R2.** Startup must fail with a validation error when auth is enabled and the key is
  missing, empty, or whitespace-only.
- **R3.** When enabled, every HTTP request whose path is not `/healthz` or `/readyz`
  must carry `Authorization: Bearer <api_key>`; this includes `/docs`, `/redoc`, and
  `/openapi.json`.
- **R4.** The scheme must match case-insensitively (`bearer`, `Bearer`); surrounding
  whitespace around the token must be ignored.
- **R5.** A missing header, a wrong scheme, a blank token, or a wrong key must return
  401 with `error.code` `unauthorized` and a `WWW-Authenticate: Bearer` header. The
  request must not reach routing.
- **R6.** Key comparison must use `hmac.compare_digest` on UTF-8 bytes.
- **R7.** When disabled, the middleware must not be mounted.
- **R8.** Non-HTTP ASGI scopes (lifespan) must pass through untouched.
- **R9.** Adding a new scheme must require only a new provider class and a change to
  `build_auth_provider`, with no change to routers.

## Design

### Configuration (`config.py`)

| Variable                   | Type          | Default | Notes                                   |
| -------------------------- | ------------- | ------- | --------------------------------------- |
| `ZVEC_SERVER_AUTH_ENABLED` | bool          | `false` | Turns the check on.                     |
| `ZVEC_SERVER_API_KEY`      | str (secret)  | none    | Required and non-blank when enabled.    |

`api_key` is a `SecretStr`, so `repr(settings)` and `model_dump()` never reveal it. A
`model_validator(mode="after")` raises when `auth_enabled` is true and the key is unset
or blank after stripping. `.env.example` documents both variables, with
`openssl rand -hex 32` as the suggested way to generate a key.

### Providers (`auth/provider.py`)

```python
class AuthProvider(ABC):
    enabled: bool = True
    @abstractmethod
    def authenticate(self, authorization: str | None) -> None: ...  # raises AuthenticationError
```

- `DisabledAuthProvider`: `enabled = False`; accepts everything.
- `ApiKeyAuthProvider(api_key)`: rejects an empty key at construction (`ValueError`).
  Splits the header on the first space, strips the token, requires scheme `bearer`
  (case-insensitive) and a non-empty token, then compares with `hmac.compare_digest`.
  Messages: `Missing Authorization header.`,
  `Invalid Authorization header; expected 'Bearer <api_key>'.`, `Invalid API key.`
- `build_auth_provider(settings)`: `DisabledAuthProvider` when off, else
  `ApiKeyAuthProvider(settings.api_key.get_secret_value())`.

A provider sees only the raw header string, so it has no framework dependency and is
unit-testable without an app.

### Middleware (`auth/middleware.py`)

`AuthMiddleware(app, provider, public_paths=PUBLIC_PATHS)` is a plain ASGI callable, not
a `BaseHTTPMiddleware`, so it adds no response-wrapping overhead and runs outside
routing. `PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})`, matched exactly against
`scope["path"]`. On `AuthenticationError` it writes a `JSONResponse` itself, because
FastAPI's exception handlers do not see middleware errors. The body comes from
`errors.build_error_payload`, the same builder the exception handlers use, so the
envelope is identical on the wire. `AuthenticationError` maps to 401 / `unauthorized`.

```http
GET /collections HTTP/1.1

HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{"error": {"code": "unauthorized", "message": "Missing Authorization header."}}
```

### Wiring (`app.py`)

`create_app` calls `build_auth_provider(resolved)` and adds `AuthMiddleware` only when
`provider.enabled`. The startup log line records `"auth": "api_key"` or `"disabled"`,
never the key. The OpenAPI description states that auth is optional and that the server
must sit behind TLS or a trusted gateway.

### Layering

`auth` depends on `errors` and `config` only. Nothing in `api`, `manager`, or `adapter`
imports `auth`; the package is wired once in `app.py`.

## Acceptance criteria

- With auth enabled, `/healthz` and `/readyz` return 200 without a header.
- `GET /collections` without a header returns 401, `error.code` `unauthorized`, and
  `WWW-Authenticate: Bearer`.
- `Basic abc` and `Bearer not-the-key` both return 401.
- With the correct bearer key, create collection, insert, and list all succeed.
- The provider accepts `bearer <key>` and `Bearer   <key>  `, and rejects no header, an
  empty header, a bare key, `Basic <key>`, `Bearer`, `Bearer ` and a wrong key.
- `Settings(auth_enabled=True)` and `Settings(auth_enabled=True, api_key="   ")` raise.
- With auth disabled, unauthenticated requests succeed and no middleware is mounted.

## Risks and open questions

- The key travels in clear text over plain HTTP. The docs and the security policy must
  say plainly that the key is not a substitute for TLS and a hardened edge.
- `hmac.compare_digest` hides the key's contents, not necessarily its length.
  Recommending a long random key keeps that moot.
- Protecting `/docs` and `/openapi.json` makes the API harder to explore when auth is
  on. Deliberate: the schema describes the whole surface.
- Exact path matching means a proxy that mounts the server under a prefix changes what
  counts as public. Revisit if prefixed deployments show up.
- Rotating the key needs a restart. Acceptable for a single static key.
- CORS preflight requests carry no credentials and will get 401; CORS is out of scope.

## Tickets

- ZS-020 — Pluggable AuthProvider with a static API-key provider
- ZS-021 — ASGI auth middleware with public health paths
