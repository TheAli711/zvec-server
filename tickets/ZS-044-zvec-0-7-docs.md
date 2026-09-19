---
id: ZS-044
title: Document the Zvec 0.7.0 upgrade, explicit close, and optimize locking
spec: SPEC-010
type: docs
priority: P1
status: in-progress
release: v0.2.0
created: 2026-09-09
---

# ZS-044: Document the Zvec 0.7.0 upgrade, explicit close, and optimize locking

## Summary

SPEC-010 changes the engine floor and two concurrency behaviours that operators and
contributors depend on. Record them in the CHANGELOG for users, and in `CLAUDE.md`
and `docs/ARCHITECTURE.md` for contributors. Those two files currently say optimize
takes the exclusive lock, which will no longer be true.

## Acceptance criteria

- [ ] `CHANGELOG.md` `[Unreleased]` *Changed* covers the Zvec 0.7.0 requirement and
      the upstream fixes it brings, non-blocking optimize with serialized
      concurrent calls, and explicit close on shutdown for rolling restarts.
- [ ] `CHANGELOG.md` *Fixed* records the mmap empty-id bug (ZS-040) with the
      `Failed to find target chunk` symptom and `ZVEC_SERVER_ENABLE_MMAP`.
- [ ] The `CLAUDE.md` concurrency invariant lists `maintain()`, the maintenance
      mutex, and explicit close under the exclusive lock. Optimize is removed from
      the exclusive-lock list.
- [ ] The lock section of `docs/ARCHITECTURE.md` matches, with a new
      "Explicit close on shutdown" bullet.

## Notes

- Depends on ZS-041, ZS-042, and ZS-043 landing first, so the docs describe
  behaviour that has actually merged.
- No README or `docs/API.md` change: the REST contract and configuration stay the
  same.
- Keep the wording about when reads are served during optimize tied to "Zvec >=
  0.7", so a future downgrade or regression is easy to spot.
