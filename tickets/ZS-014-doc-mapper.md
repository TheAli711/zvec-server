---
id: ZS-014
title: Document mapper: REST to zvec.Doc, generated ids, per-doc status
spec: SPEC-003
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-16
---

# ZS-014: Document mapper: REST to zvec.Doc, generated ids, per-doc status

## Summary

Add the document models in `models/vectors.py` (`DocIn`, `DocOut`,
`WriteResultItem`, `WriteResponse`) and `adapter/doc_mapper.py`, which translates
them to and from native `zvec.Doc` objects and turns Zvec `Status` values into
per-document results. Every document endpoint depends on this.

## Acceptance criteria

- [ ] `to_zvec_doc(DocIn)` keeps a client id or assigns `uuid4().hex`;
      `to_zvec_docs(docs)` returns the native docs and the resolved ids in input
      order.
- [ ] `from_zvec_doc(doc, include_vector)` returns `DocOut` with `score`, vectors
      as plain `list[float]` only when requested, and `fields = None` when empty.
- [ ] `status_to_item(id, status)` maps `ok()`, `code().name`, and `message()`
      into `WriteResultItem`.
- [ ] `build_write_response(ids, statuses)` pairs ids with statuses in order and
      computes `success_count` / `error_count`.
- [ ] `test_doc_mapper.py` covers id preservation, 32-char hex generation,
      resolved-id alignment, status mapping, counts, and round trips with a real
      `zvec.Doc`.

## Notes

- The response must carry the generated id; otherwise the client cannot address the
  document later.
- Native vectors may come back as numpy arrays or other sequences; coerce each
  component with `float()` so the JSON encoder never sees engine types.
- `DocOut.score` is only meaningful for search hits; fetches leave it `null`. The
  same output model will be reused by similarity search.
- Status tests can use a small fake exposing `ok()/code()/message()` so failure
  codes are testable without provoking the engine.
