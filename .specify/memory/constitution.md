<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0
Amendment: Replace Principle I (Single-File Architecture) with Focused Package
Architecture to reflect the existing src/commit_explorer/ layout. The
monolithic app.py rule was already violated by the refactor that produced
backend.py / cli.py / export.py / models.py / pr.py / providers.py / ui/app.py
along with the 73-test suite. The new principle codifies the current layout
and forbids further fragmentation without a MINOR bump.

Modified principles:
  - I. Single-File Architecture → I. Focused Package Architecture

Added sections: None
Removed sections: None

Templates reviewed:
  ✅ .specify/templates/plan-template.md — Constitution Check gate still valid; principle name change is editorial.
  ✅ .specify/templates/spec-template.md — Unchanged.
  ✅ .specify/templates/tasks-template.md — Unchanged.
  ✅ CLAUDE.md — "Architecture" section describing app.py monolith is stale; to be updated in Phase 8 (T045).

Deferred TODOs: None.
-->

# Commit Explorer (CEX) Constitution

## Core Principles

### I. Focused Package Architecture

The application lives in the `src/commit_explorer/` package. Each module owns a single
concern and SHOULD stay small (≤ ~500 lines). The current layout is normative:

- `cli.py` — argument parsing, command dispatch, progressive-disclosure wiring
- `backend.py` — Dulwich-based clone, DAG walk, diff computation
- `providers.py` — URL builders for GitHub / GitLab / Azure DevOps
- `pr.py` — PR/MR URL resolution + fork-remote plumbing
- `export.py` — text-format writers for single-commit and branch-compare views
- `format.py` — JSON / ndjson renderers and `OutputConfig` (introduced in the
  agent-friendly CLI feature; MAY be absent on older branches)
- `models.py` — `NamedTuple` domain types shared across modules
- `ui/app.py` — Textual TUI

New top-level modules MUST NOT be added without a MINOR version bump to this constitution.
Splitting an existing module (e.g. breaking `cli.py` into subpackages) also requires a
MINOR bump. Deep nesting is forbidden: the package stays flat with at most one level
(`ui/` is the only exception).

**Rationale**: The package layout reflects real concerns (network, rendering, parsing,
presentation) and keeps each file small enough to audit. A hard ceiling on module count
prevents the codebase from drifting into a deep tree that erases the "trivial audit"
property the monolithic app.py originally targeted.

### II. Protocol-First Data Access

All repository data MUST be fetched via the git wire protocol (Dulwich `porcelain.clone`),
not via provider REST or GraphQL APIs. GitHub, GitLab, and Azure DevOps MUST all use the
same clone-based approach. Provider classes are URL builders only — they MUST NOT make
HTTP API calls.

**Rationale**: A single data-access path means no per-provider API client code, no REST
pagination logic, no token scope management beyond clone auth. Uniformity across providers
is a hard requirement.

### III. Shallow Clone Performance

Clones MUST use `filter=blob:none` at all times. File content MUST NOT be fetched at clone
time — only commits and trees. Diff content is computed on demand when a commit is selected.
This MUST hold for all providers and all repository sizes.

**Rationale**: Without blob filtering, large repositories (e.g. `torvalds/linux`) would be
unusable. The shallow-clone strategy is load-bearing for the tool's core value proposition.

### IV. TUI as Primary Interface

All interactive features MUST be implemented as Textual widgets, bindings, or panels inside
`CommitExplorer(App)`. The CLI entry point (`cex`) is for pre-loading arguments only. No
web server, REST endpoint, or non-terminal GUI MUST ever be introduced.

**Rationale**: The tool is explicitly a terminal UI. Keeping the interface constraint firm
prevents scope creep into browser-based or Electron-style solutions.

### V. Simplicity & Minimal Dependencies

New dependencies MUST NOT be added unless the equivalent functionality cannot be reasonably
implemented with the existing stack (Dulwich, Textual, Rich, urllib3). YAGNI applies: do
not build abstractions for hypothetical future features. Three similar lines are preferable
to a premature abstraction.

**Rationale**: `uvx`-installable tools must have a lean dependency graph. Each new
dependency adds install time, potential breakage, and maintenance surface.

## Technology Stack

- **Language**: Python 3.11+ (type hints, `NamedTuple`, `asyncio.to_thread`)
- **Package manager**: `uv` — MUST be used for all dependency and venv management
- **TUI framework**: Textual — widgets, layouts, `@work`, bindings
- **Git library**: Dulwich (pure-Python) — clone, walk, tree diffs
- **Formatting**: Rich — ANSI→`Text` conversion, markup escaping
- **HTTP layer**: urllib3 — SSL bypass pool manager for corporate proxies
- **System dependency**: `git` binary — required on `$PATH` for graph rendering via
  `git log --graph --color=always`
- **Environment**: `python-dotenv` for `.env` token loading

Adding or removing any item from this list is a MINOR version bump to the constitution.

## Development Workflow

- Run `uv sync` before any development session to ensure dependencies are current.
- All changes MUST be validated by running `uv run cex` against at least one real
  repository before committing.
- The `--export` flag MUST remain functional as a non-interactive smoke test:
  `uv run cex owner/repo --export`.
- Commit messages MUST follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`).
- A `pytest` suite lives under `tests/`. Baseline green is a precondition for every
  new task; adding a feature without failing-then-passing tests for its new code paths
  is a governance violation.

## Governance

This constitution supersedes all other development practices for Commit Explorer. Any
amendment MUST:

1. Be made by editing `.specify/memory/constitution.md` directly.
2. Increment the version per semantic versioning:
   - **MAJOR** — principle removed, redefined, or backward-incompatible governance change.
   - **MINOR** — new principle or section added, or material expansion of existing guidance.
   - **PATCH** — clarifications, wording fixes, typo corrections.
3. Update `LAST_AMENDED_DATE` to the amendment date.
4. Propagate changes to all `.specify/templates/` files that reference the affected principle.

All feature planning (speckit workflow) MUST perform a Constitution Check gate in
`plan.md` before Phase 0 research begins.

Runtime development guidance lives in `CLAUDE.md` at the repository root.

**Version**: 1.1.0 | **Ratified**: 2026-03-07 | **Last Amended**: 2026-04-19
