# Implementation Plan: CLI Commit Export by SHA and Range

**Branch**: `20260404-211557-cli-commit-export` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/20260404-211557-cli-commit-export/spec.md`

## Summary

Add two new headless CLI modes to `app.py`: `--show <sha>` exports a single commit's full details to a `.txt` file, and `--range <base> <target>` (or `--range <sha> --depth N`) exports a linear ancestry range one file per commit. A shared `--out <folder>` flag routes output for all headless modes (defaulting to `/tmp`). All implementation goes in `app.py` using existing Dulwich, Rich, and stdlib primitives — no new dependencies.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: Dulwich (git walk + object store), Rich (console output), existing stdlib (`os`, `re`, `datetime`, `difflib`)  
**Storage**: Local filesystem — `.txt` files written to `--out` folder (default `/tmp`)  
**Testing**: Manual via `uv run cex owner/repo --show <sha>` and `--range`  
**Target Platform**: Linux/macOS terminal  
**Project Type**: CLI tool (single-file `app.py`)  
**Performance Goals**: Single commit export completes in well under 30 seconds; range exports show per-commit progress on stderr  
**Constraints**: No new dependencies; all changes confined to `app.py`; `filter=blob:none` unchanged  
**Scale/Scope**: Ranges up to hundreds of commits; no cap enforced

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Single-File Architecture | ✅ PASS | All new code goes in `app.py` |
| II. Protocol-First Data Access | ✅ PASS | SHA resolution and range walk use Dulwich object store and `get_walker()` |
| III. Shallow Clone Performance | ✅ PASS | `filter=blob:none` unchanged; `get_detail()` fetches blobs on-demand as today |
| IV. TUI as Primary Interface | ✅ PASS | New modes are headless CLI extensions, not new GUI surfaces |
| V. Simplicity & Minimal Dependencies | ✅ PASS | No new packages; `_slugify()` helper is stdlib-only |

All gates pass. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/20260404-211557-cli-commit-export/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-flags.md     # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
app.py                   # Single file — all changes here
```

All new functions and modifications are additions to `app.py`. No new files, packages, or modules.
