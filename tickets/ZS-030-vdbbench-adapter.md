---
id: ZS-030
title: VectorDBBench REST adapter
spec: SPEC-007
type: feature
priority: P2
status: in-progress
release: v0.1.1
created: 2026-06-25
---

# ZS-030: VectorDBBench REST adapter

## Summary

Implement Track B of SPEC-007: a VectorDBBench client plugin that runs the
community-standard harness against a live Zvec Server over REST. Its QPS, recall, and
build-time figures can then be compared directly with zvec.org's published Cohere
1M/10M runs. This track measures only the served path. The in-process breakdown is
Track A's job.

## Acceptance criteria

- [ ] `benchmarks/vdbbench/zvec_rest_client.py` defines `ZvecRest`, `ZvecRestConfig`
      (`host`, `port`, `timeout=600`), and `ZvecRestHNSWConfig` (`metric_type`,
      `M=15`, `efConstruction=200`, `ef=180`).
- [ ] The client creates an `hnsw` `VECTOR_FP32` collection with an indexed `INT64`
      `id` field. It inserts through `/docs/insert` using string ids, runs flush and
      then optimize in `optimize()`, and returns int ids from `search_embedding`.
- [ ] `filters={"id": X}` becomes the filter `id >= X`. With no filter, the client
      sends `null`.
- [ ] Signatures accept both VectorDBBench `v0.0.20` and `main`: `**kwargs`,
      `optimize(data_size=...)`, and `payload_profile`.
- [ ] The module imports without `vectordb_bench` installed. Constructing
      `ZvecRest` without it raises an `ImportError` that points to the README.
- [ ] `benchmarks/vdbbench/README.md` covers installing in a separate venv, starting
      the server, registering the classes on a `TaskConfig` at runtime, the Cohere
      1M/10M cases, and filtered cases.

## Notes

- Keep VectorDBBench out of the `bench` extra. It pulls in Streamlit and many DB
  drivers.
- VectorDBBench has no plugin discovery. Register at runtime by overriding
  `init_cls`, `config_cls`, and `case_config_cls` on an existing `DB` enum member,
  rather than forking the package.
- Open the `httpx.Client` only inside `init()`. The harness may pickle the client to
  ship it to worker processes.
- Map `L2`, `COSINE`, and `IP` to `l2`, `cosine`, and `ip`, and reject anything else.
  `need_normalize_cosine()` returns `False`.
