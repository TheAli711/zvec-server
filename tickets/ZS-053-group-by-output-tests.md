---
id: ZS-053
title: Group-by honors include_vector and output_fields
spec: SPEC-012
type: test
priority: P2
status: todo
release: v0.2.0
created: 2026-09-14
---

# ZS-053: Group-by honors include_vector and output_fields

## Summary

SPEC-012 R7 says `include_vector` and `output_fields` apply to every group-by hit
exactly as in `/search`, and that grouping still works when `output_fields` leaves
out the `group_by` field. The endpoint tests in ZS-052 exercise `output_fields` only
with the group field itself and never request vectors. Add an integration test that
pins both options down together.

## Acceptance criteria

- [ ] A group-by on `category` with `include_vector: true` and
      `output_fields: ["year"]` returns `200`.
- [ ] Every hit across all groups has exactly `{"year"}` in `fields`, even though
      the grouping field is not requested.
- [ ] Every hit's `vectors.embedding` matches the stored vector for its id
      (approximate float comparison).
- [ ] All seeded documents are accounted for across the groups (three hits for the
      three sample documents with the default `topk_per_group`).

## Notes

- Lives in `tests/integration/test_search_api.py`, reusing the `sample_docs` fixture
  (ids `a`, `b`, `c`; categories `tech` / `news`) and the `_seed` helper.
- Compare vectors with `pytest.approx`; the engine may not round-trip floats
  bit-for-bit.
- If Zvec needs the group field in the output to group, this test is where it shows
  up; the fix would belong in the adapter, not the test.
