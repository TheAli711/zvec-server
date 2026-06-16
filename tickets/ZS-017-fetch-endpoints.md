---
id: ZS-017
title: Fetch documents by ids and get a document by id
spec: SPEC-003
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-16
---

# ZS-017: Fetch documents by ids and get a document by id

## Summary

Add `POST /collections/{name}/docs/fetch` for batch lookup by id and
`GET /collections/{name}/docs/{doc_id}` for a single document. Both run under the
collection's shared read lock so they proceed concurrently with other reads.

## Acceptance criteria

- [ ] `FetchRequest`: `ids` (min 1), `output_fields` (null = all),
      `include_vector` (default `false`); `FetchResponse` is `{"docs": {id:
      DocOut}}`, with missing ids omitted.
- [ ] `operations.fetch` passes `output_fields` and `include_vector` to
      `collection.fetch` and maps engine errors (`ValueError` → `400`, others →
      `500`).
- [ ] `GET /docs/{doc_id}` accepts `include_vector` and repeated `output_fields`
      query params and returns the bare `DocOut`.
- [ ] A missing document on GET → `404 document_not_found` with
      `details: {"collection": name, "id": doc_id}`.
- [ ] Integration tests cover batch fetch with a missing id and vectors compared
      within FP32 tolerance, single GET, and the 404 path.

## Notes

- The GET route reuses the fetch path with a one-element `FetchRequest` rather than
  a separate engine call, so both endpoints behave the same.
- Returned vectors reflect storage precision; tests must compare approximately.
- Route order in `api/vectors.py`: `docs/fetch` is POST and `docs/{doc_id}` is GET,
  so they do not collide.
