# Implementation Plan: Agent-Friendly CLI (Progressive Disclosure)

**Branch**: `20260418-212347-agent-friendly-cli` | **Date**: 2026-04-18 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/20260418-212347-agent-friendly-cli/spec.md`

---

## Summary

Reshape the `cex` CLI so that every command defaults to the smallest safe output (file list only, 50-commit page, no diff), provides explicit opt-in flags for richer views (`--diff`, `--file`, `--limit`), and always includes a `Next:` hint when output was capped. A new `--format json/ndjson` flag gives AI agents schema-stable output they can parse without regex. The changes touch `cli.py`, `export.py`, and add a new `format.py`; the TUI, backend, and provider layers are untouched.

---

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: Dulwich (git wire protocol), Textual (TUI), Rich (ANSI/markup), urllib3 (SSL proxy), python-dotenv, argparse (stdlib), json (stdlib), subprocess (git binary)  
**Storage**: N/A — no persistent state beyond temporary clone directories  
**Testing**: pytest 8+; baseline 73 tests in `tests/`  
**Target Platform**: Linux/macOS/Windows terminal; agent (non-TTY) context is the optimisation target  
**Project Type**: CLI tool with TUI  
**Performance Goals**: Any default-flag command against a 1M+ commit repo produces ≤ 60 lines of output (SC-001)  
**Constraints**: No new runtime dependencies; `git` binary required on `$PATH`; `filter=blob:none` always applied at clone time  
**Scale/Scope**: Any public/private git repository; potentially millions of commits

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Single-File Architecture (`app.py`) | ⚠ STALE | Constitution says all code lives in `app.py`. The codebase was already refactored into `src/commit_explorer/` package before this feature branch. Constitution must be amended (MINOR bump) to reflect the package layout before this plan is executed. |
| II. Protocol-First Data Access | ✓ Pass | `--file PATH` on `--export` uses `git log --follow` subprocess — consistent with existing graph rendering pattern. No new provider API calls. |
| III. Shallow Clone Performance | ✓ Pass | `filter=blob:none` unchanged. File-history filtering happens post-clone against already-fetched commit graph. |
| IV. TUI as Primary Interface | ✓ Pass | New flags extend `cli.py` (already exists); TUI (`ui/app.py`) is untouched. |
| V. Simplicity & Minimal Dependencies | ✓ Pass | `--format json` uses stdlib `json`. `--format ndjson` same. No new packages. |

**GATE RESULT**: Blocked on Principle I amendment. **Required action before Phase 0**: Update `.specify/memory/constitution.md` to replace the single-file `app.py` rule with the current `src/commit_explorer/` package layout (MINOR version bump to 1.1.0).

---

## Project Structure

### Documentation (this feature)

```text
specs/20260418-212347-agent-friendly-cli/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
│   └── cli-flags.md
├── quickstart.md        ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code (affected files only)

```text
src/commit_explorer/
├── cli.py          ← all 5 handler functions + _build_parser() rewritten
├── export.py       ← write_export / write_commit_export gain stream + section params
├── format.py       ← NEW (phase 5): JSON/ndjson rendering; OutputConfig lives here
├── backend.py      ← untouched (file-history uses git subprocess, not dulwich walk)
├── models.py       ← untouched (OutputConfig is not a domain model)
└── ui/             ← untouched

tests/
├── test_exports.py        ← extended: stdout mode, section-flag combos
├── test_cli.py            ← extended: new flags, pagination footer, JSON schema
├── test_format.py         ← NEW (phase 5): JSON schema validation, ndjson line count
└── test_file_history.py   ← NEW (phase 3): --export --file filter correctness
```

**Structure Decision**: Single-package layout under `src/commit_explorer/`. New `format.py` added in phase 5. All other modules touched only via additions, not structural changes.

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Constitution I (single-file) | Already violated by the prior refactor; not introduced by this feature | Reverting to `app.py` would delete 73 tests and the package structure established in the prior session |
| New `format.py` module (phase 5) | JSON rendering logic is 150+ lines; embedding it in `export.py` creates a 500-line file doing two unrelated jobs | Single-file rule already broken; a focused module is preferable to a bloated `export.py` |

---

## Phase 0: Research

*All NEEDS CLARIFICATION items from Technical Context resolved here.*

### Research 1 — File-History Filter: Dulwich vs. `git log --follow`

**Decision**: Use `git log --follow --format=%H -- PATH` subprocess call.

**Rationale**: Dulwich's `get_walker` does not implement rename-following. It would require manually computing tree diffs for every commit to detect renames — O(N) blob comparisons, expensive on large repos. The existing graph renderer already delegates to `git log --graph` subprocess; `--export --file` is the same pattern extended with `--follow`.

**Alternatives considered**:
- Dulwich walker with `tree_changes` per commit: works for non-renames, fails silently when file was renamed. Rejected.
- Dulwich + manual rename heuristic (similarity ratio): complex, not equivalent to git's rename detection. Rejected.

**Implementation**: In `_export`, before rendering the graph, run:
```
git --git-dir TMPDIR log --follow --format=%H -- PATH
```
Collect the resulting SHAs into a set. Pass this set to the graph renderer as an allowlist; commits not in the set are skipped from output.

---

### Research 2 — Writer Refactor: Section-by-Section Control

**Decision**: Add boolean section parameters to `write_export` and `write_commit_export`. Do NOT introduce a render/model split yet (that is Phase 5).

**Rationale**: Phase 2 (progressive disclosure flags) only needs to omit sections from the text output. The simplest change is `write_export(..., include_diff=True, include_files=True)`. The render/model split is needed only for `--format json`, which is Phase 5. Doing the split in Phase 2 is premature.

**How it fits with Phase 5**: In Phase 5, `format.py` will build a dict from the same `BranchComparison`/`CommitDetail` objects independently of `export.py`. `export.py` keeps the text rendering; `format.py` owns JSON rendering. They share no code — clean separation.

---

### Research 3 — Stdout Routing Without Breaking Existing Tests

**Decision**: Default `out_dir` to `None` for all commands; `None` means stdout. `write_export`/`write_commit_export` gain an optional `stream` parameter; when `stream` is given they write to it and return `None`, else they write to file and return the path.

**CLI handler changes**:
- Remove the `/tmp` fallback from `main()`
- Each handler (`_show`, `_compare`, `_pr_review`, `_range`) passes `stream=sys.stdout` when `out_dir is None`
- When `out_dir` is set, behaviour is unchanged (write file, print path)

**Test impact**: `test_exports.py` tests call `write_export(result, out_dir=tmp_path)` — these remain valid. New tests call `write_export(result, stream=io.StringIO())` to capture stdout output.

---

### Research 4 — Pagination Footer: Reconstructing the `Next:` Command

**Decision**: Each paginated command receives `limit` and `offset` as explicit arguments. The footer is assembled from the original `owner/repo`, `--export`/`--range`, `--limit N`, and `--offset M+N`. No argv introspection needed.

**Format**:
```
[50 of 1,234,567 commits shown]
Next: cex owner/repo --export --offset 50 --limit 50
```

For `--file PATH`, the filter arg is also echoed in the footer:
```
Next: cex owner/repo --export --file src/x.py --offset 50 --limit 50
```

---

## Phase 1: Design & Contracts

### Data Model — `data-model.md`

See [data-model.md](./data-model.md).

**New type: `OutputConfig`** — a plain dataclass (not a domain model) that bundles all rendering options across all commands. Lives in `format.py` (phase 5) but its fields are defined here to guide phase 1–4 implementation.

```
OutputConfig:
  stream:       IO[str] | None   # None → write file; set → write to stream
  out_dir:      str | None       # None → use stream
  include_diff: bool             # False by default
  include_files:bool             # True by default
  file_filter:  list[str]        # empty → all files; non-empty → filter to these paths
  max_lines:    int              # 0 = unbounded; 500 when include_diff=True
  max_bytes:    int              # 0 = unbounded
  limit:        int              # 0 = unbounded; 50 for export/range
  offset:       int              # 0 = start from beginning
  fmt:          str              # "text" | "json" | "ndjson"
  color:        str              # "auto" | "always" | "never"
```

This config is assembled in `main()` from parsed args and passed into every handler. Handlers pass relevant fields to writers.

---

### Interface Contracts — `contracts/cli-flags.md`

See [contracts/cli-flags.md](./contracts/cli-flags.md).

The public interface for the feature is the CLI flag schema. All changes to flags are breaking API changes from the user's perspective. The contract file enumerates every flag, its type, default, scope, and interaction rules.

Key contract rules:
- `--diff` and `--no-diff` are mutually exclusive; `--no-diff` wins if both present.
- `--file PATH` on `--show`/`--compare`/`--pr`/`--range` implies `--diff` for those paths.
- `--file PATH` on `--export` is a commit filter, not a diff flag; it does NOT imply `--diff`.
- `--limit 0` and `--max-lines 0` both mean "unbounded."
- `--format json` and `--format ndjson` suppress all ANSI codes regardless of `--color`.
- `--out PATH` and `--format json` compose: JSON goes to file, path goes to stdout.

---

### Quickstart for Agents — `quickstart.md`

See [quickstart.md](./quickstart.md).

A short guide written for AI agents (or developers integrating `cex` into agent workflows). Covers:
1. Install: `uv tool install commit-explorer` or `uvx commit-explorer`
2. The five-rung ladder in one table
3. The three canonical agent flows (repo summary, file history, PR review)
4. JSON schema reference
5. How to follow `Next:` hints
