# Security Policy

## A note on the threat model

Zvec Server is a **thin storage layer** intended to run on a **trusted network**.
Please understand the following before deploying it:

- **Authentication is optional and minimal.** It is **off by default**. When
  enabled (`ZVEC_SERVER_AUTH_ENABLED=true` with `ZVEC_SERVER_API_KEY`), it is a
  **single static API key** checked against an `Authorization: Bearer` header —
  there is no per-user identity, roles, scopes, rotation, or revocation. With
  auth **disabled**, every endpoint is open to anyone who can reach the server.
- **There is no authorization model.** Any client holding the key has full
  read/write/delete access to every collection.
- **There is no rate limiting, quota, or multi-tenancy.**
- The server speaks plain HTTP and should **never** be exposed directly to the
  public internet — the API key is sent in clear text without TLS in front of it.

The built-in API key is a convenience for simple/trusted deployments; it is
**not** a substitute for a hardened edge. Deploy it behind one or more of:

- a private network / VPC with no public ingress,
- an authenticating reverse proxy or API gateway (e.g. one that enforces
  API keys, mTLS, OAuth, or your identity provider),
- network policies / firewall rules restricting access to trusted clients,
- TLS termination at the proxy (the server speaks plain HTTP).

## Supported versions

This project is pre-1.0 and under active development. Security fixes are applied
to the latest released version and the `main` branch.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, report privately using one of:

- GitHub's **["Report a vulnerability"](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)**
  feature on this repository (Security → Advisories), or
- email **ali7112001@gmail.com**.

Please include, where possible:

- a description of the vulnerability and its impact,
- steps to reproduce (proof-of-concept, requests, configuration),
- affected version(s) and environment,
- any suggested remediation.

## What to expect

- We aim to **acknowledge** your report within **3 business days**.
- We will work with you to understand and validate the issue and keep you
  updated on remediation progress.
- Once a fix is available, we will coordinate disclosure and credit you (unless
  you prefer to remain anonymous).

Please act in good faith, avoid privacy violations and service disruption, and
give us reasonable time to address the issue before any public disclosure.
