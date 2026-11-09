---
id: ZS-073
title: Accept Zvec 0.8 document ids, including in GET /docs/{doc_id}
spec: SPEC-015
type: feature
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-073: Accept Zvec 0.8 document ids, including in GET /docs/{doc_id}

## Summary

Zvec 0.8 accepts any non-empty UTF-8 document id up to 1,024 bytes without NUL or
newline. 0.7 allowed at most 64 characters from a narrow ASCII set. The server
passes ids through unchanged, so the bump enables this. But
`GET /collections/{name}/docs/{doc_id}` can't route an id that contains `/`. Use a
`path` converter and test the new rules end to end.

## Acceptance criteria

- [x] `GET /collections/{name}/docs/{doc_id:path}` returns documents whose id
      contains `/`, sent literally or as `%2F`.
- [x] Integration tests: ids with spaces, `/`, `,`, `'`, non-ASCII, and exactly
      1,024 bytes insert, fetch, `GET`, and search. 1,025 bytes, a newline, NUL,
      and `""` return `400`.
- [x] Scalar field names up to 64 ASCII bytes create successfully (was 32), and
      non-ASCII names return `422`.
- [x] docs/API.md states the id and field-name rules.

## Notes

- Collection names stay `^[A-Za-z0-9_-]{3,64}$` (SPEC-015 non-goal).

## Resolution

Changed the route to `/docs/{doc_id:path}`. The models needed no change because
ids were already passed through. Integration tests cover the relaxed ids
(spaces, URL-like, punctuation, emoji/CJK, 1,024 bytes ASCII and multi-byte)
through insert, fetch, GET (encoded and literal `/`), and search, plus 400s for
1,025 bytes, newline, NUL, and `""`. They also cover the 64-byte field-name
limit and the 422 for 65 bytes or non-ASCII. docs/API.md documents the rules.
