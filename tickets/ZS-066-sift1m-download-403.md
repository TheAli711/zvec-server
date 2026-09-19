---
id: ZS-066
title: SIFT1M download is rejected with 403
spec: SPEC-007
type: bug
priority: P2
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-066: SIFT1M download is rejected with 403

## Summary

The `sift1m` benchmark scenario (SPEC-007) auto-downloads
`http://ann-benchmarks.com/sift-128-euclidean.hdf5` on first use. The mirror
answers `403 Forbidden` to Python's default `urllib` User-Agent, so the scenario
fails before loading any data on a machine without a cached copy. This blocks the
SIFT1M runs planned under SPEC-014.

## Reproduction

1. Start from a clean dataset cache (no `benchmarks/.datasets/` copy of the file).
2. Run `uv run python -m benchmarks run --scenario sift1m` (or `quant --scenario
   sift1m`).

Observed: `datasets._download()` calls `urllib.request.urlretrieve(url, tmp)`, which
raises `urllib.error.HTTPError: HTTP Error 403: Forbidden`; nothing is cached and
the run aborts.

Expected: the file downloads into `benchmarks/.datasets/` and the scenario runs.

## Acceptance criteria

- [x] The download sends an explicit User-Agent the mirror accepts.
- [x] The file is still written to a `.part` temp file and renamed only once
      complete, so an interrupted download is never mistaken for a cached copy.
- [x] The body is streamed to disk in chunks rather than read into memory.
- [x] A cached file is reused without any network request.
- [x] CHANGELOG `Fixed` entry added.

## Notes

- Module: `benchmarks/datasets.py` (`_download`). `urlretrieve` can't set headers;
  switch to `urllib.request.Request` + `urlopen` and copy with
  `shutil.copyfileobj`.
- Stay on the standard library; the bench extra does not need an HTTP client for
  this.
- Not covered by CI (the benchmark suite is lint-only there); verify by hand.

## Resolution

`_download()` now builds a `urllib.request.Request` with a
`User-Agent: zvec-server-benchmarks` header and streams the response to the `.part`
file with `shutil.copyfileobj` in 1 MiB chunks before renaming it. The `sift1m`
download succeeds; the CHANGELOG notes the fix.
