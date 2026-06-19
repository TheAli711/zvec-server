---
id: ZS-005
title: Error hierarchy and consistent JSON error envelope
spec: SPEC-001
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-14
---

# ZS-005: Error hierarchy and consistent JSON error envelope

## Summary

Define `zvec_server/errors.py`: a `ZvecServerError` base carrying `status_code`,
`error_code`, `message`, and optional `details`, the initial subclasses, the
`ErrorResponse` model, and FastAPI handlers that render every failure as
`{"error": {"code", "message", "details"}}`. Clients should be able to branch on
`code` without parsing messages.

## Acceptance criteria

- [ ] Subclasses with fixed status/code: `CollectionNotFoundError` (404),
      `DocumentNotFoundError` (404), `CollectionAlreadyExistsError` (409),
      `SchemaValidationError` (422), `InvalidArgumentError` (400),
      `CollectionUnavailableError` (503), `ZvecOperationError` (500); the base
      defaults to 500 `internal_error`.
- [ ] `build_error_payload(code, message, details)` renders the envelope with
      `details` dropped when `None`, and is the only renderer in the codebase.
- [ ] `RequestValidationError` → 422 `validation_error` with the Pydantic errors
      under `details.errors`; Starlette `HTTPException` → its status with
      `http_error` and the exception detail as the message.
- [ ] Any other exception → 500 `internal_error`, message "An unexpected error
      occurred.", traceback logged; app errors with status >= 500 are logged with
      `exc_info`.
- [ ] `ErrorResponse` is re-exported from `models/common.py` for OpenAPI use.

## Notes

- `errors.py` must stay a leaf module (it is imported by `db`, `adapter`, and
  `manager`); import FastAPI types only under `TYPE_CHECKING` or inside
  `register_exception_handlers`.
- Keep `build_error_payload` public: a middleware running outside the exception
  handler stack (e.g. an auth check) must emit identical bodies.
- Codes are part of the API contract; renaming one is a breaking change.
