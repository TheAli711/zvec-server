---
id: ZS-008
title: Zvec adapter: runtime init, enum and schema mapping
spec: SPEC-002
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-15
---

# ZS-008: Zvec adapter: runtime init, enum and schema mapping

## Summary

Create the `zvec_server.adapter` package, the only place allowed to `import zvec`.
This ticket covers the process-wide engine init and the translation of API schema
specs (plain strings and Pydantic models) into native Zvec enums, index params, and
a `zvec.CollectionSchema`. Invalid input must surface as `SchemaValidationError`
(422), never as a raw engine exception.

## Acceptance criteria

- [ ] `runtime.init_zvec(log_level, log_dir, memory_limit_mb, query_threads,
      optimize_threads)` initializes the engine once per process; later calls are
      no-ops and a `RuntimeError` from a repeat `zvec.init` is treated as success.
- [ ] Log levels map from Python names (`WARNING` → `WARN`, `CRITICAL` → `FATAL`);
      unknown values fall back to `WARN`.
- [ ] `enums.py` exposes `VECTOR_DATA_TYPES`, `SCALAR_DATA_TYPES`, `INDEX_TYPES`,
      case-insensitive `parse_data_type`/`parse_metric_type` (aliases `dot`,
      `inner_product` → `IP`; `euclidean` → `L2`) and `validate_index_type`, each
      raising `SchemaValidationError` with `details.valid`.
- [ ] `schema_mapper.build_collection_schema(name, vectors, fields)` builds HNSW
      (`m`, `ef_construction`), IVF (`n_list`, `n_iters`), or flat index params,
      rejects non-int or bool params, and adds an inverted index for
      `indexed: true` scalars.
- [ ] A vector spec with a scalar dtype (or the reverse) is rejected;
      `primary_vector_info(req)` returns the first vector's `(name, dim)`.
- [ ] Unit tests in `test_enums.py` and `test_schema_mapper.py` run against the
      real `zvec` module.

## Notes

- The init guard matters for tests, which build many apps in one interpreter.
- Unrecognized keys in `params` are ignored rather than rejected, so clients can
  send a superset without breaking; only recognized keys are type-checked.
- Keep `models/` free of `zvec` imports; the mapper takes our models and returns
  native objects.
