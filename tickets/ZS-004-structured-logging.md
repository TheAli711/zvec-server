---
id: ZS-004
title: Structured logging (JSON or console)
spec: SPEC-001
type: feature
priority: P1
status: in-progress
release: v0.1.0
created: 2026-06-14
---

# ZS-004: Structured logging (JSON or console)

## Summary

Add `zvec_server/logging.py` with `configure_logging(level, fmt)` and
`get_logger(name)`. Production needs one JSON object per line for log aggregation;
local development needs a compact readable line. Uvicorn's own loggers must use the
same handler so access and error logs are not in a second format.

## Acceptance criteria

- [ ] `fmt="json"` uses python-json-logger with keys `timestamp`, `level`,
      `name`, `message`, plus any `extra={...}` fields passed by the caller.
- [ ] `fmt="console"` uses `%(asctime)s %(levelname)-8s %(name)s | %(message)s`.
- [ ] A single stdout handler replaces the root logger's handlers; the level is
      applied case-insensitively.
- [ ] `uvicorn`, `uvicorn.error`, and `uvicorn.access` get the same handler and
      level, with `propagate = False` to avoid duplicate lines.
- [ ] The entry point passes `log_config=None` to Uvicorn so it does not install
      its default config over ours.

## Notes

- Call sites should log structured context through `extra=` (e.g.
  `{"collection": name}`) rather than formatting it into the message.
- `configure_logging` runs first in the lifespan and may run once per app built in
  tests; it must be safe to call repeatedly (replace handlers, do not append).
- The Zvec engine keeps its own log files, controlled separately by
  `ZVEC_SERVER_ZVEC_LOG_DIR`; this ticket covers Python logging only.
