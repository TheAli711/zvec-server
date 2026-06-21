---
id: ZS-021
title: ASGI auth middleware with public health paths
spec: SPEC-005
type: feature
priority: P1
status: in-progress
release: v0.1.0
created: 2026-06-17
---

# ZS-021: ASGI auth middleware with public health paths

## Summary

Enforce the provider from ZS-020 on every HTTP request. The middleware must run before
routing, leave `/healthz` and `/readyz` open for orchestrators, and answer failures with
the standard JSON error envelope and a `WWW-Authenticate: Bearer` header. It is mounted
only when auth is enabled, so the default configuration pays nothing.

## Acceptance criteria

- [ ] `auth/middleware.py` provides a plain ASGI `AuthMiddleware` (not
      `BaseHTTPMiddleware`) with `PUBLIC_PATHS = {"/healthz", "/readyz"}`; non-HTTP
      scopes and public paths pass straight through.
- [ ] A rejected request gets 401, `error.code` `unauthorized`, and
      `WWW-Authenticate: Bearer`, with the body built by `errors.build_error_payload`.
- [ ] `create_app` mounts the middleware only when `provider.enabled`; the startup log
      reports `auth` as `api_key` or `disabled`.
- [ ] With auth on, `/docs` and `/openapi.json` also require the key.
- [ ] `tests/integration/test_auth.py` covers public probes, a missing header, a wrong
      scheme, a wrong key, a valid key, a full create + insert flow, and the default
      disabled app.

## Notes

- Middleware errors never reach FastAPI's exception handlers, so the middleware must
  render the response itself. Reuse the shared payload builder instead of hand-writing
  the JSON, so the envelope cannot drift.
- Match public paths exactly against `scope["path"]`. A proxy mounting the server under
  a prefix would change that; out of scope for v0.1.0.
- Mention auth in the OpenAPI description, including the advice to deploy behind TLS or
  a trusted gateway.
- Depends on ZS-005 (error envelope) and ZS-006 (health endpoints).
