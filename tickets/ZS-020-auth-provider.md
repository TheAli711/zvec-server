---
id: ZS-020
title: Pluggable AuthProvider with a static API-key provider
spec: SPEC-005
type: feature
priority: P1
status: in-progress
release: v0.1.0
created: 2026-06-17
---

# ZS-020: Pluggable AuthProvider with a static API-key provider

## Summary

Add the configuration and the decision logic for SPEC-005: two settings
(`ZVEC_SERVER_AUTH_ENABLED`, `ZVEC_SERVER_API_KEY`), an `AuthProvider` abstraction that
validates a raw `Authorization` header, a no-op provider for the default, and a
bearer-token provider that checks one static key in constant time. The HTTP wiring is
ZS-021.

## Acceptance criteria

- [ ] `Settings` has `auth_enabled: bool = False` and `api_key: SecretStr | None`; a
      validator fails startup when auth is enabled and the key is unset or blank.
- [ ] `auth/provider.py` defines `AuthProvider` (`enabled`,
      `authenticate(authorization)`), `DisabledAuthProvider`, and `ApiKeyAuthProvider`,
      which rejects an empty key at construction.
- [ ] `ApiKeyAuthProvider` accepts a case-insensitive `Bearer` scheme with surrounding
      whitespace, compares with `hmac.compare_digest`, and raises `AuthenticationError`
      (401, `unauthorized`) for a missing header, wrong scheme, blank token, or wrong key.
- [ ] `build_auth_provider(settings)` returns the disabled provider when off and the
      API-key provider otherwise.
- [ ] `.env.example` documents both variables, off by default.
- [ ] `tests/unit/test_auth.py` covers the providers, the factory, and the settings
      validation, including a parametrized set of bad headers.

## Notes

- Keep providers framework-free: they take the header string, not a request object, so
  they unit-test without an app and a future scheme only needs a new class plus a branch
  in `build_auth_provider`.
- The key must never be logged or dumped; `SecretStr` covers `repr` and `model_dump`.
  Unwrap it only in `build_auth_provider`.
- `auth/__init__.py` lists the public names in `__all__`; `api`, `manager`, and
  `adapter` must not import `auth`.
- Risk: `compare_digest` can reveal key length but not contents; recommend
  `openssl rand -hex 32`.
