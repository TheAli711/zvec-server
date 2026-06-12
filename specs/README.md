# Specs, tickets, and the tracker

Zvec Server is built **spec-first**. Every feature starts as a written spec,
the spec is broken down into tickets, and the tickets drive the work. All three
live in this repository, next to the code they describe, so the history of *why*
something was built is versioned with *what* was built.

```
specs/SPEC-NNN-*.md   →   tickets/ZS-NNN-*.md   →   TRACKER.md
   (what and why)          (units of work)          (generated board)
```

## 1. Specs (`specs/`)

A spec describes one coherent capability: the problem, goals and non-goals,
requirements, the proposed API/design, and acceptance criteria. It is written
**before** implementation and reviewed like code.

- File name: `specs/SPEC-NNN-short-slug.md`, numbered sequentially.
- Start from [`_templates/spec.md`](./_templates/spec.md).
- Lifecycle (`status:` in the front matter):

  | Status        | Meaning                                                    |
  | ------------- | ---------------------------------------------------------- |
  | `draft`       | Being written or discussed. No tickets yet.                |
  | `accepted`    | Agreed. Broken down into tickets; work may start.          |
  | `implemented` | Every planned ticket is `done`.                            |
  | `superseded`  | Replaced by a later spec (link it in the body).            |
  | `rejected`    | Decided against. Kept for the record.                      |

- A spec moves `draft → accepted` in the same commit that files its tickets and
  adds the `## Tickets` section.
- Specs must respect the project scope in [`CONTRIBUTING.md`](../CONTRIBUTING.md):
  a thin storage layer over Zvec — no embedding generation, no multi-tenancy.

## 2. Tickets (`tickets/`)

A ticket is one reviewable unit of work — ideally one commit or one small PR.

- File name: `tickets/ZS-NNN-short-slug.md`, numbered sequentially across the
  whole project (IDs are never reused).
- Start from [`_templates/ticket.md`](./_templates/ticket.md).
- Every ticket names its parent spec (`spec: SPEC-NNN`). Bugs found after a spec
  is implemented are filed against that spec; they do not reopen it.
- `type:` is one of `feature`, `bug`, `chore`, `docs`, `test`.
- `priority:` is `P0` (blocks a release), `P1` (planned for the release), or
  `P2` (nice to have).
- `release:` is the version the ticket is planned to ship in.
- Lifecycle (`status:`):

  | Status        | Meaning                                                   |
  | ------------- | --------------------------------------------------------- |
  | `backlog`     | Filed, not scheduled (e.g. blocked on an upstream fix).   |
  | `todo`        | Scheduled for a release.                                  |
  | `in-progress` | Being worked on.                                          |
  | `done`        | Merged. Acceptance criteria ticked; `closed:` date set.   |
  | `wontfix`     | Closed without a change (explain in `## Resolution`).     |

- When a ticket is closed: tick its acceptance criteria, set `status: done` and
  `closed: YYYY-MM-DD`, and add a short `## Resolution` section at the end.

## 3. Tracker (`TRACKER.md`)

`TRACKER.md` is a board **generated** from the front matter of every spec and
ticket. Never edit it by hand:

```bash
python scripts/tracker.py           # regenerate TRACKER.md
python scripts/tracker.py --check   # fail if it is stale or a file is invalid (CI)
```

The script uses only the standard library, and `--check` also validates the
front matter (unique IDs, known statuses, every ticket's spec exists, `done`
tickets have a `closed:` date).

## Commits and pull requests

- Reference tickets in commit trailers: `Closes: ZS-012` when the commit
  finishes a ticket, `Refs: ZS-012` when it only contributes to one.
- The commit that finishes a ticket also flips its status and regenerates
  `TRACKER.md`, so the board never drifts from `main`.
- Dependency bumps (Dependabot) and `release:` commits don't need a ticket.

## Worked example

Illustrative IDs only:

1. Draft `specs/SPEC-042-bulk-import.md` (`status: draft`) and open it for
   review.
2. Once agreed, set `status: accepted`, file `tickets/ZS-120…ZS-122`, list them
   under `## Tickets`, and run `python scripts/tracker.py`.
3. Move a ticket to `in-progress` when you start it.
4. Land the change with `Closes: ZS-120` in the commit, the ticket flipped to
   `done`, and the tracker regenerated.
5. When the last planned ticket closes, set the spec to `implemented`.
