---
id: ZS-079
title: Inserting into a VECTOR_INT8 field returns 500
spec: SPEC-003
type: bug
priority: P1
status: backlog
release: v0.3.1
created: 2026-11-09
---

# ZS-079: Inserting into a VECTOR_INT8 field returns 500

## Summary

`VECTOR_INT8` is an advertised vector dtype (README, docs/API.md), and creating
a field with it succeeds (metric `l2`/`ip`). Every insert fails, though:
`doc_mapper` passes the JSON list straight to `zvec.Doc`, and Zvec rejects it
("expected VECTOR_INT8, got <class 'list'>"). The server returns `500
zvec_operation_error`.

## Reproduction

Create `{"name": "i8col", "vectors": [{"name": "e", "dim": 4, "dtype":
"VECTOR_INT8", "metric": "l2"}]}`, then insert `{"id": "a", "vectors": {"e": [1,
2, 3, 4]}}`. The response is `500`. Verified on 0.8.1.

## Acceptance criteria

- [ ] Inserts into `VECTOR_INT8` fields succeed when the values are integers in
      -128..127, presumably by converting to the type Zvec expects in the adapter.
      Out-of-range or non-integer values return `400`.
- [ ] Fetch, search, and export round-trip the values.
- [ ] Find out whether `cosine` is unsupported for `VECTOR_INT8` (create returns
      `422`) and document it.

## Notes

- Found in review of SPEC-015. It predates the 0.8.1 upgrade.
