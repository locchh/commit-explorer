# Implementation Plan: Branch Comparison View

**Branch**: `20260329-205124-branch-compare` | **Date**: 2026-03-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/20260329-205124-branch-compare/spec.md`

## Summary

Add a dedicated compare screen to Commit Explorer that lets users type two branch names, fetches remote tracking refs, and displays a scrollable panel showing: file diff summary, commits unique to the target branch, and hunk-level conflict detection. Triggered by a key binding from the main view; results exportable to `.txt`.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Textual (Screen, widgets, bindings), Dulwich (fetch, object store), Rich (markup), subprocess (git binary)
**Storage**: N/A — bare clone in existing tmpdir; no persistent state
**Testing**: Manual via TUI (no test suite per constitution)
**Target Platform**: Terminal (Linux / macOS / Windows)
**Project Type**: TUI desktop app (single file)
**Performance Goals**: Comparison results in <15s for branches with up to 200 diverging commits
**Constraints**: filter=blob:none at all times; blob content fetched on demand for conflicting files only; all code in app.py
**Scale/Scope**: Single user, one repo session at a time

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Single-File Architecture | ✅ PASS | CompareScreen, new NamedTuples, and _GitBackend methods all added to app.py |
| II. Protocol-First Data Access | ✅ PASS | Fetch via subprocess `git fetch` on existing tmpdir; no REST/GraphQL APIs |
| III. Shallow Clone Performance | ✅ PASS | filter=blob:none maintained; blob content fetched on demand for conflicting files only — same pattern as existing `get_detail()` |
| IV. TUI as Primary Interface | ✅ PASS | CompareScreen is a Textual `Screen` subclass; key binding pushes/pops screen |
| V. Simplicity & Minimal Dependencies | ✅ PASS | No new dependencies; reuses subprocess git (already used in `_build_graph_from_git`) and Dulwich |

All gates pass. No Complexity Tracking required.

## Project Structure

### Documentation (this feature)

```text
specs/20260329-205124-branch-compare/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
│   ├── key-bindings.md
│   └── export-format.md
├── quickstart.md        ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
app.py                   # Single file — all new code added here
```

All new types, backend methods, and UI components are added directly to `app.py` per the Single-File Architecture principle.
