---
id: ZS-056
title: Auth coverage for the export and group-by routes
spec: SPEC-013
type: test
priority: P2
status: todo
release: v0.2.0
created: 2026-09-15
---

# ZS-056: Auth coverage for the export and group-by routes

## Summary

The auth middleware (SPEC-005) protects every path outside `PUBLIC_PATHS`, so the new
`GET /collections/{name}/export` and `POST /collections/{name}/search/group-by`
routes should already require the API key. Nothing proves it: `test_auth.py` predates
both. Add a parametrized test so a future change to routing or public paths can't
silently expose them (SPEC-013 R11).

## Acceptance criteria

- [ ] One parametrized test covers `GET .../export` and `POST .../search/group-by`
      on an auth-enabled app.
- [ ] A request with no `Authorization` header returns `401`.
- [ ] A request with a wrong bearer token returns `401`.
- [ ] The same request with the correct key returns `200`.
- [ ] The collection used by the test is created through the authenticated API, so
      the `200` case exercises the real handler rather than a `404`.

## Notes

- Add to `tests/integration/test_auth.py`, reusing the `auth_client` fixture and the
  `_bearer()` helper.
- The group-by case runs on an empty collection (`groups: []`) and the export case
  returns an empty body; both are `200`, which is all this test needs.
- Group-by belongs to SPEC-012, but its auth coverage is filed here so both new
  routes are covered in one place.
