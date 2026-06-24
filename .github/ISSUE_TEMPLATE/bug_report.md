---
name: Bug report
about: Report a problem so we can fix it
title: "[Bug] "
labels: bug
assignees: ""
---

## Description

A clear and concise description of what the bug is.

## Steps to reproduce

1. Start the server with `...`
2. Send request `...` (include the HTTP method, path, and JSON body)
3. See error

Please include the exact request/response where possible:

```bash
curl -sS -X POST http://localhost:8000/collections \
  -H 'Content-Type: application/json' \
  -d '{ ... }'
```

```json
// Response received
```

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened (include error messages and stack traces).

## Environment

- Zvec Server version: <!-- e.g. 0.1.0 -->
- Install method: <!-- uv / Docker / docker compose -->
- Python version: <!-- e.g. 3.12.x (not needed for Docker) -->
- OS / architecture: <!-- e.g. Ubuntu 24.04 x86_64, macOS arm64 -->
- `zvec` version: <!-- from `uv pip show zvec`, if known -->

## Relevant logs

<details>
<summary>Server logs</summary>

```
paste logs here
```

</details>

## Additional context

Anything else that might help (collection schema, filter strings, etc.).
