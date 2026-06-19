---
id: ZS-006
title: Liveness and readiness endpoints
spec: SPEC-001
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-14
---

# ZS-006: Liveness and readiness endpoints

## Summary

Add `GET /healthz` and `GET /readyz` in `api/health.py` with typed response models
in `models/common.py`. Orchestrators need to distinguish "process is alive" from
"startup finished and collections are loaded", and operators need to see when
registered collections failed to open.

## Acceptance criteria

- [ ] `GET /healthz` returns `200 {"status": "ok"}` and does no I/O.
- [ ] `GET /readyz` returns `503` (`http_error`, "Service not ready.") while
      `app.state.ready` is false or no manager is attached.
- [ ] Once ready, `/readyz` returns `200 {"status": "ready", "collections_loaded":
      N, "collections_unavailable": M}` from the manager's `counts()`, and stays
      `200` when `M > 0`.
- [ ] `HealthResponse` and `ReadyResponse` carry OpenAPI examples; both routes are
      tagged `health`.
- [ ] Integration tests cover both probes and that `/openapi.json` is served.

## Notes

- Returning `200` with unavailable collections is deliberate: one collection with
  missing data must not pull the whole instance out of rotation. Document that
  alerting should key off `collections_unavailable`.
- Both probes must stay reachable without credentials if an API key is ever
  enabled; keep them outside any auth-protected router.
- The collection counts depend on the collection registry being attached to
  `app.state` by the lifespan (ZS-002).
