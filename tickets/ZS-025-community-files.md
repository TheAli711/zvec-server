---
id: ZS-025
title: Contributor and community files
spec: SPEC-006
type: docs
priority: P2
status: todo
release: v0.1.0
created: 2026-06-18
---

# ZS-025: Contributor and community files

## Summary

Add the files an open-source project needs before its first release: a contributing
guide that encodes the thin-storage-layer scope and the quality gates, a security policy
with a realistic threat model and a private reporting channel, a code of conduct, issue
and PR templates, and a changelog. They must agree with each other and with the README.

## Acceptance criteria

- [ ] `CONTRIBUTING.md` covers scope, setup (`uv sync --extra dev`, optional pre-commit),
      the four quality gates, coding standards and layering, the docs-in-the-same-PR
      rule, the PR process, and bug reporting.
- [ ] `SECURITY.md` states the threat model (trusted network, optional single key, no
      authorization or rate limiting, plain HTTP), supported versions, private reporting
      via GitHub advisories or email, and a 3-business-day acknowledgement target.
- [ ] `CODE_OF_CONDUCT.md` adopts Contributor Covenant 2.1 with an enforcement contact.
- [ ] `.github/ISSUE_TEMPLATE/bug_report.md` asks for the exact request/response and
      environment; `feature_request.md` includes a scope check.
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` has a change-type list and a checklist for
      ruff, format, mypy, pytest, docs, CHANGELOG, and scope.
- [ ] `CHANGELOG.md` follows Keep a Changelog and SemVer, with `[Unreleased]` and a
      `0.1.0` entry listing everything shipped.

## Notes

- The quality gates must match CI (ZS-007) exactly: `ruff check`, `ruff format --check`,
  `mypy`, `pytest`, on Python 3.12 and 3.13.
- The security policy must be honest about SPEC-005: the key is a convenience, not an
  edge; recommend a private network, an authenticating gateway, and TLS at the proxy.
- Security reports must never go through public issues; say so in CONTRIBUTING too.
- Risk: the contact address is personal until the project has a shared one.
