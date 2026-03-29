<!--
SYNC IMPACT REPORT
==================
Version change: (unfilled template) → 1.0.0
Initial constitution — all placeholders replaced for the first time.

Modified principles: N/A (first fill)
Added sections: Core Principles, Technology Stack, Development Workflow, Governance
Removed sections: N/A

Templates reviewed:
  ✅ .specify/templates/plan-template.md — Constitution Check section already present; gates align with principles below.
  ✅ .specify/templates/spec-template.md — Functional Requirements use MUST/SHOULD language consistent with this constitution.
  ✅ .specify/templates/tasks-template.md — Phase structure and parallel task guidance align with Simplicity and single-file principles.
  ✅ .claude/commands/speckit.constitution.md — Command file references generic `.specify/memory/constitution.md`; no agent-specific name leakage.

Deferred TODOs: None — all fields resolved from codebase context.
-->

# Commit Explorer (CEX) Constitution

## Core Principles

### I. Single-File Architecture

The entire application MUST live in `app.py`. No splitting into packages, submodules, or
separate modules unless absolutely unavoidable. All types, providers, git backend, graph
rendering, and Textual UI belong in that single file.

**Rationale**: Single-file layout enables zero-install usage via `uvx`, trivial code audits,
and eliminates the cognitive overhead of multi-module navigation. The ~900-line budget
is a soft ceiling — violate it only with explicit justification.

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
- No test suite exists at this time; acceptance testing is manual via the TUI. If a
  test suite is introduced in future, it SHOULD use `pytest`.

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

**Version**: 1.0.0 | **Ratified**: 2026-03-07 | **Last Amended**: 2026-03-29
