---
id: ZS-057
title: Document streaming export
spec: SPEC-013
type: docs
priority: P1
status: todo
release: v0.2.0
created: 2026-09-15
---

# ZS-057: Document streaming export

## Summary

Document the export endpoint (SPEC-013 R12) so users can rely on it for backups: the
API reference (query params, line shape, snapshot semantics, the in-band error line),
the README, the architecture notes on export cursors, the `CLAUDE.md` invariant for
future drop/close paths, and an export step in both examples that shows how to
detect a truncated export.

## Acceptance criteria

- [ ] `docs/API.md` documents `GET /collections/{name}/export`: `include_vector`
      and `output_fields`, a `curl > file` example, sample lines, snapshot
      semantics, the final `{"error": ...}` line, and unspecified order.
- [ ] The README route table lists the route; key features mention streaming export
      and that exports never block writes.
- [ ] `docs/ARCHITECTURE.md` explains per-batch locking and `close_cursors()`, and
      the module map lists `/export`.
- [ ] `CLAUDE.md` states that any new drop/close path must call `close_cursors()`
      under the exclusive lock first.
- [ ] `examples/curl_examples.sh` streams an export; `examples/python_client.py`
      streams it line by line with `httpx` and raises on an error line.

## Notes

- The in-band error line is the one thing a client can get wrong: a `200` does not
  prove the export completed. Say so in the API reference and show the check in the
  Python example.
- In the curl script, call `curl` directly rather than through the `req` helper
  (which pretty-prints JSON with `jq` when present) so the raw NDJSON lines are
  shown, and keep the optional auth header expansion safe under bash 3.2
  (`"${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"}"`).
