---
id: ZS-038
title: Recovery delay settings and docs
spec: SPEC-009
type: feature
priority: P1
status: done
release: v0.1.2
created: 2026-07-02
closed: 2026-07-08
---

# ZS-038: Recovery delay settings and docs

## Summary

Make the SPEC-009 backoff configurable and document the behaviour. Operators need to
tune how quickly a collection is retried after a failed open, and to understand why a
collection can show `available: false` for a while after a restart and then recover
without anyone intervening.

## Acceptance criteria

- [x] `Settings.collection_recovery_initial_delay_seconds: float = 30.0` and
      `collection_recovery_max_delay_seconds: float = 300.0` are read from
      `ZVEC_SERVER_COLLECTION_RECOVERY_INITIAL_DELAY_SECONDS` and
      `ZVEC_SERVER_COLLECTION_RECOVERY_MAX_DELAY_SECONDS`.
- [x] `docs/CONFIGURATION.md` has a "Collection recovery" section with a table of both
      settings. It explains the rolling-restart race and how `/readyz` reports
      unavailable collections in the meantime.
- [x] The configuration table in `README.md` lists both variables.
- [x] `.env.example` has a commented-out "Collection recovery" block with the
      defaults.
- [x] CHANGELOG has an Added entry. The registry invariant in CLAUDE.md now describes
      `start_recovery()`, the backoff settings, and cancellation.
- [x] Tests can shrink both delays through `Settings(...)`, so recovery tests run in
      milliseconds.

## Notes

- Defaults: the first retry comes after 30 s, which lets a typical previous instance
  finish shutting down, so a one-off race clears on the first retry. The 300 s cap
  bounds the log noise from a collection that stays broken.
- Both settings are plain floats with no validation. Whether to add bounds is an open
  question in SPEC-009.
- Bumping the release version to 0.1.2 is release housekeeping and is not part of
  this ticket.

## Resolution

Added both settings to `config.py` and documented them in `docs/CONFIGURATION.md`,
`README.md`, and `.env.example`, with a CHANGELOG entry under 0.1.2. The values are
not range-checked. The sample `.env` in `docs/CONFIGURATION.md` uses shorter,
illustrative delays (`1.0` / `60.0`) rather than the defaults.
