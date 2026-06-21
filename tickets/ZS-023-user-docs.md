---
id: ZS-023
title: User docs: README, API, configuration, architecture
spec: SPEC-006
type: docs
priority: P1
status: in-progress
release: v0.1.0
created: 2026-06-18
---

# ZS-023: User docs: README, API, configuration, architecture

## Summary

Write the user-facing documentation for v0.1.0: a README that states scope and gets a
new user running, and three references under `docs/` covering the REST API, every
configuration variable, and the architecture. The docs must match the code exactly
(paths, field names, defaults, status codes) and repeat the rules users most often trip
over: single worker, client-supplied vectors only, and the SQL-like filter syntax.

## Acceptance criteria

- [ ] `README.md` has "What it is", "What it is NOT", key features, quickstart (uv,
      Docker Compose, smoke test), route tables for health, collections, and documents,
      a configuration table, authentication, an architecture overview, development
      commands, and links to docs and examples.
- [ ] `docs/API.md` documents conventions, authentication, the error envelope and code
      table, filter syntax, data types, index types and metrics, and every endpoint with
      request/response JSON.
- [ ] `docs/CONFIGURATION.md` lists every `ZVEC_SERVER_*` variable by section
      (storage, HTTP, logging, engine, auth) with type, default, and meaning, plus an
      example `.env`.
- [ ] `docs/ARCHITECTURE.md` covers design principles, module layout, import direction,
      startup and shutdown, request lifecycle, concurrency, and persistence.
- [ ] Names, defaults, and status codes in the docs match `config.py`, `errors.py`, and
      the routers.

## Notes

- Sources of truth: `config.py` for variables and defaults, `errors.py` for the code
  table, `models/` for request/response shapes. Cross-check against the live `/docs`.
- Filter syntax must be spelled out once in `docs/API.md` (single `=`, single-quoted
  strings, `AND`/`OR`/`NOT`/`IN`/`BETWEEN`/`LIKE`) and linked from the README.
- The auth sections follow SPEC-005 and must say the key is no substitute for TLS.
- Mention that `WARNING` maps to Zvec's `WARN` log level.
- Risk: drift. Keep the README tables short and point to `docs/API.md` for detail.
