---
id: ZS-002
title: App factory, lifespan, and zvec-server entry point
spec: SPEC-001
type: feature
priority: P0
status: done
release: v0.1.0
created: 2026-06-14
closed: 2026-06-24
---

# ZS-002: App factory, lifespan, and zvec-server entry point

## Summary

Add `create_app(settings=None)` in `zvec_server/app.py` with a lifespan that wires
the process-wide singletons in a fixed order and tears them down on shutdown, plus
the `zvec-server` console script. Tests depend on being able to build several apps
in one interpreter, each pointed at its own temporary data directory.

## Acceptance criteria

- [x] Lifespan order: `configure_logging` → engine init (once per process) →
      `settings.ensure_directories()` → metadata store `connect()` → collection
      manager `load_all()` → `app.state.ready = True`. Shutdown sets `ready = False`,
      then closes the manager and the store.
- [x] `settings`, `store`, and `manager` live on `app.state`; `deps.get_manager`
      and `deps.get_metadata` expose them to routers.
- [x] `zvec-server` and `python -m zvec_server` call `uvicorn.run` with
      `"zvec_server.app:create_app"`, `factory=True`, `workers=1`,
      `log_config=None`, and host/port from settings.
- [x] OpenAPI is titled `Zvec Server`, versioned from `__version__`, with tags
      `health`, `collections`, `documents`; exception handlers and routers are
      registered in the factory.
- [x] `tests/conftest.py` provides `settings` (tmp `data_dir`) and `client`
      (`TestClient` running the lifespan) fixtures.

## Notes

- The single worker is intentional: open collection handles are process-local.
  Document this in the `main()` docstring so nobody "fixes" it.
- Keep a module-level `app = create_app()` for `uvicorn zvec_server.app:app`; it
  must not do I/O at import (all I/O is in the lifespan).
- Engine init must tolerate repeated app startups in one process (tests); the guard
  belongs in the adapter, not here.
- Depends on ZS-003 (settings), ZS-004 (logging), ZS-005 (handlers).

## Resolution

Added `app.py`, `__main__.py`, and `deps.py` with the lifespan and entry points
described above, and a startup log line reporting host and port. The factory also
mounts the collection and document routers as those features landed.
