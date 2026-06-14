---
id: ZS-002
title: App factory, lifespan, and zvec-server entry point
spec: SPEC-001
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-14
---

# ZS-002: App factory, lifespan, and zvec-server entry point

## Summary

Add `create_app(settings=None)` in `zvec_server/app.py` with a lifespan that wires
the process-wide singletons in a fixed order and tears them down on shutdown, plus
the `zvec-server` console script. Tests depend on being able to build several apps
in one interpreter, each pointed at its own temporary data directory.

## Acceptance criteria

- [ ] Lifespan order: `configure_logging` → engine init (once per process) →
      `settings.ensure_directories()` → metadata store `connect()` → collection
      manager `load_all()` → `app.state.ready = True`. Shutdown sets `ready = False`,
      then closes the manager and the store.
- [ ] `settings`, `store`, and `manager` live on `app.state`; `deps.get_manager`
      and `deps.get_metadata` expose them to routers.
- [ ] `zvec-server` and `python -m zvec_server` call `uvicorn.run` with
      `"zvec_server.app:create_app"`, `factory=True`, `workers=1`,
      `log_config=None`, and host/port from settings.
- [ ] OpenAPI is titled `Zvec Server`, versioned from `__version__`, with tags
      `health`, `collections`, `documents`; exception handlers and routers are
      registered in the factory.
- [ ] `tests/conftest.py` provides `settings` (tmp `data_dir`) and `client`
      (`TestClient` running the lifespan) fixtures.

## Notes

- The single worker is intentional: open collection handles are process-local.
  Document this in the `main()` docstring so nobody "fixes" it.
- Keep a module-level `app = create_app()` for `uvicorn zvec_server.app:app`; it
  must not do I/O at import (all I/O is in the lifespan).
- Engine init must tolerate repeated app startups in one process (tests); the guard
  belongs in the adapter, not here.
- Depends on ZS-003 (settings), ZS-004 (logging), ZS-005 (handlers).
