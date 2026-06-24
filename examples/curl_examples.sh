#!/usr/bin/env bash
#
# End-to-end example of the Zvec Server REST API using curl.
#
# Walks through: create collection -> insert -> search (with filter) ->
# fetch by id -> update -> delete -> drop collection.
#
# Run a server first (see the project README), then:
#
#     ./examples/curl_examples.sh
#
# Point at a different server with the ZVEC_SERVER_URL environment variable:
#
#     ZVEC_SERVER_URL=http://localhost:8000 ./examples/curl_examples.sh
#
# If the server has authentication enabled, supply the API key; it is sent as a
# bearer token on every request:
#
#     ZVEC_SERVER_API_KEY=your-key ./examples/curl_examples.sh
#
# Requires: curl. (jq is optional; if present, responses are pretty-printed.)
#
# NOTE: the server stores client-supplied vectors only -- it does not generate
# embeddings -- so the vectors below are hand-written for illustration.

set -euo pipefail

BASE_URL="${ZVEC_SERVER_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
COLLECTION="articles_example"

# When set, send the API key as a bearer token on every request.
AUTH_HEADER=()
if [[ -n "${ZVEC_SERVER_API_KEY:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${ZVEC_SERVER_API_KEY}")
fi

# Pretty-print JSON with jq if available, otherwise pass through unchanged.
if command -v jq >/dev/null 2>&1; then
  pp() { jq .; }
else
  pp() { cat; }
fi

# Wrapper: fail loudly on HTTP errors (>= 400) but still show the body.
req() {
  local method="$1" path="$2" body="${3:-}"
  local url="${BASE_URL}${path}"
  local out http
  # Note: the `[@]+...` guard keeps the empty-array case safe under `set -u`
  # on bash 3.2 (the default /bin/bash on macOS).
  if [[ -n "${body}" ]]; then
    out="$(curl -sS -w $'\n%{http_code}' -X "${method}" "${url}" \
      "${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"}" -H 'Content-Type: application/json' -d "${body}")"
  else
    out="$(curl -sS -w $'\n%{http_code}' -X "${method}" "${url}" \
      "${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"}")"
  fi
  http="${out##*$'\n'}"
  printf '%s\n' "${out%$'\n'*}" | pp
  if [[ "${http}" -ge 400 ]]; then
    echo "  -> HTTP ${http} (request failed)" >&2
    return 1
  fi
}

echo "== Health check (${BASE_URL}) =="
req GET /healthz

echo
echo "== Create collection '${COLLECTION}' =="
req POST /collections '{
  "name": "'"${COLLECTION}"'",
  "vectors": [
    {
      "name": "embedding",
      "dim": 4,
      "dtype": "VECTOR_FP32",
      "index": "hnsw",
      "metric": "cosine",
      "params": { "m": 16, "ef_construction": 200 }
    }
  ],
  "fields": [
    { "name": "category", "dtype": "STRING", "indexed": true },
    { "name": "year", "dtype": "INT32", "indexed": true }
  ],
  "options": { "enable_mmap": true }
}'

echo
echo "== Insert documents =="
req POST "/collections/${COLLECTION}/docs/insert" '{
  "docs": [
    { "id": "a1", "vectors": { "embedding": [0.10, 0.20, 0.30, 0.40] }, "fields": { "category": "tech", "year": 2021 } },
    { "id": "a2", "vectors": { "embedding": [0.12, 0.22, 0.29, 0.41] }, "fields": { "category": "tech", "year": 2023 } },
    { "id": "a3", "vectors": { "embedding": [0.90, 0.10, 0.05, 0.02] }, "fields": { "category": "science", "year": 2019 } }
  ]
}'

echo
echo "== Search (filter: category = 'tech' AND year > 2020) =="
# Filters use Zvec's SQL-like syntax: single '=', single-quoted strings,
# operators AND/OR/NOT/IN/BETWEEN/LIKE. NOT Python '=='.
req POST "/collections/${COLLECTION}/search" '{
  "queries": [
    { "field": "embedding", "vector": [0.11, 0.21, 0.30, 0.40], "params": { "ef": 64 } }
  ],
  "topk": 3,
  "filter": "category = '\''tech'\'' AND year > 2020",
  "include_vector": false,
  "output_fields": ["category", "year"]
}'

echo
echo "== Fetch document by id (a1, include vector) =="
req GET "/collections/${COLLECTION}/docs/a1?include_vector=true"

echo
echo "== Update document (a1 -> year 2022) =="
req POST "/collections/${COLLECTION}/docs/update" '{
  "docs": [
    { "id": "a1", "vectors": { "embedding": [0.10, 0.20, 0.30, 0.40] }, "fields": { "category": "tech", "year": 2022 } }
  ]
}'

echo
echo "== Delete document (a3) =="
req POST "/collections/${COLLECTION}/docs/delete" '{ "ids": ["a3"] }'

echo
echo "== Drop collection '${COLLECTION}' =="
req DELETE "/collections/${COLLECTION}"

echo
echo "Done."
