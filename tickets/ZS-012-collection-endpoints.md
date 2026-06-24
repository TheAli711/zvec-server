---
id: ZS-012
title: Collection endpoints: create, list, get, drop
spec: SPEC-002
type: feature
priority: P0
status: done
release: v0.1.0
created: 2026-06-15
closed: 2026-06-24
---

# ZS-012: Collection endpoints: create, list, get, drop

## Summary

Expose collection CRUD in `api/collections.py`: `POST /collections`,
`GET /collections`, `GET /collections/{name}`, and `DELETE /collections/{name}`,
backed by `CollectionManager.create`/`list`/`info`/`drop` and the request/response
models in `models/collections.py`.

## Acceptance criteria

- [x] `CreateCollectionRequest` validates `name` against `^[A-Za-z0-9_-]{1,128}$`,
      requires at least one vector with `dim > 0`, and defaults vector specs to
      `VECTOR_FP32` / `hnsw` / `cosine`.
- [x] Create checks the registry (`409`), builds the schema (`422
      schema_validation_error`), creates the collection under `collections_dir`,
      stores the record with the Zvec schema snapshot and effective
      `enable_mmap`, and returns `201 CollectionInfo`.
- [x] If the metadata insert fails, the new on-disk collection is destroyed before
      the error propagates.
- [x] `GET /collections` returns `CollectionListResponse`; `GET
      /collections/{name}` returns `CollectionInfo` (404 if unknown).
- [x] `DELETE` destroys an open collection (or removes the directory of an
      unavailable one), deletes the metadata row and registry entry, and returns
      `{"message": "Collection '<name>' deleted."}`; unknown → `404`.
- [x] Integration tests cover create, duplicate, invalid name/dtype, list, get,
      and delete, including 404 paths.

## Notes

- `MessageResponse` in `models/common.py` is the shared acknowledgement body for
  delete, flush, and optimize.
- The engine's `ValueError` on create (a collection already at that path) maps to
  `409`; other engine failures map to `500 zvec_operation_error`.
- The drop path for unavailable entries must not require an open handle.
- `embedding_model` is metadata only; the server never calls a model.

## Resolution

Added the collection models, `CollectionManager.create`/`drop`, and the four
routes in `api/collections.py`, with integration tests in
`test_collections_api.py` and model tests in `test_models.py`.
