---
id: ZS-054
title: Document group-by search
spec: SPEC-012
type: docs
priority: P1
status: done
release: v0.2.0
created: 2026-09-14
closed: 2026-09-19
---

# ZS-054: Document group-by search

## Summary

Make group-by search discoverable (SPEC-012 R11): the API reference entry with the
request field table, example request and response, and the string-value and
null-group rules; the README route table and key features; the architecture module
map; and a group-by step in both runnable examples so users see it end to end.

## Acceptance criteria

- [x] `docs/API.md` documents `POST /collections/{name}/search/group-by`: fields,
      defaults, bounds, an example, string `value`s, the `""` null group, and the
      `400` cases.
- [x] The README route table lists the route and the key-features list mentions
      group-by search.
- [x] `docs/ARCHITECTURE.md` lists group-by in the `operations.py` and
      `api/vectors.py` entries of the module map.
- [x] `examples/curl_examples.sh` and `examples/python_client.py` run a group-by
      (best hit per `category`) after the plain search, and `examples/README.md`
      describes the updated flow.

## Notes

- Keep the RAG framing from SPEC-012: chunks grouped by `doc_id` so one long document
  can't crowd out the rest.
- The examples' collection has a `category` field; group on it with
  `topk_per_group: 1` so the output is short.
- The curl script must stay safe under macOS bash 3.2 (reuse the existing `req`
  helper).

## Resolution

The API reference section, route-table row, and CHANGELOG entry shipped with the
endpoint in ZS-052. This ticket added the README key-features bullet, the
architecture module-map entries, and the group-by step in the curl script, the
Python client (`group_by_search`), and `examples/README.md`, in the same docs pass as
the export docs (ZS-057).
