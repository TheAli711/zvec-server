---
id: ZS-062
title: Collection names outside 3-64 characters are misreported as 409
spec: SPEC-002
type: bug
priority: P1
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-062: Collection names outside 3-64 characters are misreported as 409

## Summary

`CreateCollectionRequest` accepts names matching `^[A-Za-z0-9_-]{1,128}$`, but Zvec
rejects names outside 3-64 characters with a `ValueError`.
`adapter/collections.create_collection` maps **every** `ValueError` to
`CollectionAlreadyExistsError`. So a bad name, or any schema the engine rejects,
returns a misleading `409 collection_already_exists` for a collection that does
not exist.

## Reproduction

```bash
curl -sX POST localhost:8000/collections -H 'content-type: application/json' \
  -d '{"name": "ab", "vectors": [{"name": "e", "dim": 4}]}'
```

Observed: `409 collection_already_exists`, "A collection already exists at
'.../collections/ab'". A 65-character name behaves the same way, and
`GET /collections/ab` returns 404.

Expected: `422 validation_error` stating the 3-64 character rule. Engine schema
rejections that are not path conflicts should also return `422`.

## Acceptance criteria

- [x] The name pattern is `^[A-Za-z0-9_-]{3,64}$` in the model, its description,
      the validation message, and `docs/API.md`.
- [x] `POST /collections` with a 2-character or 65-character name returns 422.
- [x] `create_collection` maps a `ValueError` to 409 only for Zvec's
      "path validate failed" (the path already exists). Any other `ValueError`
      becomes `SchemaValidationError` (422).
- [x] Model unit tests cover the new boundaries: `abc` and 64 characters are valid;
      `ab` and 65 characters are invalid.
- [x] A CHANGELOG *Fixed* entry is added, and the breaking tightening is noted for
      the release.

## Notes

- Modules: `models/collections.py`, `adapter/collections.py`, and `docs/API.md`.
  The platform `RuntimeError` mapping from ZS-048 stays as is.
- Tightening the pattern cannot strand existing data. Names outside 3-64 never
  reached the engine successfully, so no stored collection can have one.

## Resolution

Tightened the name pattern to 3-64 characters and made `create_collection` tell
Zvec's existing-path `ValueError` (409) apart from schema rejections (now 422).
Model and integration tests were added for the boundaries. The API reference and
CHANGELOG were updated, and the release notes call out the tighter name rule.
