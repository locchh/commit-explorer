# Tasks: Branch Comparison View

**Input**: Design documents from `/specs/20260329-205124-branch-compare/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Structure**: All code lives in `app.py` (single-file architecture per constitution).
**Tests**: Not requested — manual validation via TUI per constitution.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: Verify the environment is ready before touching app.py.

- [X] T001 Verify `git merge-tree --write-tree` is available (`git --version` ≥ 2.38) and `uv sync` is current

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the new types, the CompareScreen skeleton, and the key binding to `app.py`. Must be complete before any user story phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add `ConflictFile` and `BranchComparison` NamedTuples to the Types section of `app.py` (after existing `RepoInfo` type)
- [X] T003 Add `fetch_all()` method to `_GitBackend` in `app.py` — runs `git --git-dir <tmpdir> fetch --all --quiet` via subprocess; raises on failure
- [X] T004 Add `CompareScreen(Screen)` skeleton class to `app.py` — two `Input` widgets (base branch, target branch), a "Compare" `Button`, a `ScrollableContainer` with a `Static` results widget, `Escape` binding wired to `self.dismiss()`
- [X] T005 Add `Binding("c", "compare", "Compare")` to `CommitExplorer.BINDINGS` in `app.py` and add `action_compare()` method that calls `self.push_screen(CompareScreen(self._backend))` — guard: only active when `self._owner` is set

**Checkpoint**: `uv run cex owner/repo` — pressing `c` opens a blank compare screen; `Escape` returns to main view.

---

## Phase 3: User Story 1 — Compare Two Remote Branches (Priority: P1) 🎯 MVP

**Goal**: Fetch remote refs, compare two `origin/*` branches, display file diff summary and unique commits in a scrollable panel.

**Independent Test**: Load a repo, press `c`, enter `main` and a feature branch, press Compare. Verify the file list and commit list match `git diff --stat` and `git log main..feature` output.

- [X] T006 [US1] Implement `_GitBackend.compare_branches(base, target)` in `app.py` — runs `fetch_all()`, then three subprocess calls: `git diff origin/<base> origin/<target> --stat --no-color`, `git diff origin/<base> origin/<target> --shortstat --no-color`, `git log origin/<base>..origin/<target> --format="%H%x00%s%x00%aN%x00%ad" --date=short --no-color`; parses results into `BranchComparison` (conflicts=[], shallow_warning=False for now)
- [X] T007 [US1] Add shallow clone detection inside `compare_branches()` in `app.py` — run `git --git-dir <tmpdir> rev-parse --is-shallow-repository`; set `BranchComparison.shallow_warning = True` if output is `"true"`; if `merge-base` fails, set warning and continue
- [X] T008 [US1] Implement `CompareScreen._run_comparison()` as a `@work` async method in `app.py` — validates both inputs non-empty, calls `await asyncio.to_thread(self._backend.compare_branches, base, target)`, renders diff summary and unique commits sections into the results `Static`
- [X] T009 [US1] Wire `CompareScreen` inputs and Compare button in `app.py` — `Input.Submitted` on either input and `Button.Pressed` on Compare both trigger `_run_comparison()`; show `LoadingIndicator` during work; show `notify()` on error

**Checkpoint**: US1 fully testable independently — compare screen shows real diff and commit data.

---

## Phase 4: User Story 2 — Detect Merge Conflicts (Priority: P2)

**Goal**: After diff/log, detect whether branches can be merged cleanly; if not, list conflicting files with hunk-level conflict markers.

**Independent Test**: Use a repo with a known conflict between two branches — verify the conflicting file appears with `<<<<<<<` markers. Use a clean repo — verify "Clean merge" indicator.

- [X] T010 [US2] Add `_GitBackend.detect_conflicts(base, target)` method to `app.py` — attempts `git --git-dir <tmpdir> -c core.bare=true merge-tree --write-tree --no-messages origin/<base> origin/<target>`; on failure or git < 2.38, falls back to classic `git merge-tree $(git merge-base origin/<base> origin/<target>) origin/<base> origin/<target>`; parses output into `list[ConflictFile]`
- [X] T011 [US2] Integrate `detect_conflicts()` into `_GitBackend.compare_branches()` in `app.py` — call after log step; populate `BranchComparison.conflicts`; if merge-base is unavailable (shallow), set `shallow_warning=True` and set `conflicts=[]`
- [X] T012 [US2] Add conflicts section to `CompareScreen._run_comparison()` results rendering in `app.py` — if `conflicts` is empty: show `"✓ Clean merge — no conflicts detected"`; otherwise list each `ConflictFile.filename` followed by its `conflict_text` in a clearly delimited block

**Checkpoint**: US2 works independently — conflict section appears correctly on both conflicting and clean repos.

---

## Phase 5: User Story 3 — Export Comparison Report (Priority: P3)

**Goal**: Write the current comparison result to a `.txt` file and notify the user of the file path.

**Independent Test**: After a comparison, press Export. Verify a `.txt` file appears in CWD with the correct filename and all three sections (diff summary, commits, conflicts).

- [X] T013 [US3] Add an "Export" `Button` to `CompareScreen.compose()` in `app.py` — placed above the results scroll container; initially `disabled=True`
- [X] T014 [US3] Implement `_write_export(result: BranchComparison) -> str` function in `app.py` — builds `.txt` content per `contracts/export-format.md`; filename: `compare-{base}-{target}-{YYYYMMDD}.txt` with `/` replaced by `-`; writes to CWD; returns file path
- [X] T015 [US3] Wire Export button in `CompareScreen` in `app.py` — `Button.Pressed` calls `_write_export(self._last_result)`; show `self.notify(f"Exported to {path}")` on success; show error notification on write failure; enable button only after a comparison completes (store result in `self._last_result`)

**Checkpoint**: US3 works independently — export file contains correct content matching what the screen shows.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T016 [P] Add input validation to `CompareScreen` in `app.py` — strip whitespace from branch names; show inline error if either field is empty when Compare is pressed; show `notify()` if `origin/<branch>` ref does not exist after fetch
- [X] T017 [P] Add shallow-warning banner to `CompareScreen` results rendering in `app.py` — if `BranchComparison.shallow_warning` is True, prepend `"⚠ Shallow clone — commit log and conflict results may be incomplete"` at the top of the results panel
- [X] T018 Manual validation per `specs/20260329-205124-branch-compare/quickstart.md` against at least one real repository — confirmed all sections render correctly and export matches screen content
- [X] T019 Enhanced `_write_export()` to produce detailed report: full `git diff` patch, full `git log --stat`, changed files with +/- counts, PR metadata header when available
- [X] T020 Added `--compare BASE TARGET` CLI flag to `main()` — clones repo, compares branches, prints summary, writes `.txt` without launching TUI
- [X] T021 Fixed `filter=blob:none` partial clone: switched to `git diff --name-status` for file list (tree-only), fetch blobs on demand before `--shortstat` and full diff
- [X] T022 Added PR/MR review: `--pr <URL>` CLI flag + PR number input in TUI; resolves base/head via GitHub/GitLab API; handles cross-fork PRs via `pr-head` remote; export filename encodes PR number; PR title + description shown in TUI and export

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **blocks all user story phases**
- **Phase 3 (US1)**: Depends on Phase 2
- **Phase 4 (US2)**: Depends on Phase 3 (conflict results are integrated into `compare_branches()`)
- **Phase 5 (US3)**: Depends on Phase 2; can start in parallel with US2 after US1 complete
- **Phase 6 (Polish)**: Depends on all US phases

### Parallel Opportunities

Within Phase 2: T003, T004, T005 can be written in parallel (different methods/classes in app.py); T002 must precede T003–T005 (types used by all).

Within Phase 3: T006 and T008 layout can be drafted in parallel; T008 depends on T006 result type.

T013 (Export button layout) can be added during Phase 3 and wired in Phase 5.

---

## Parallel Example: Phase 2

```
Task: "Add ConflictFile and BranchComparison NamedTuples to app.py"  ← do first
Then in parallel:
  Task: "Add fetch_all() to _GitBackend in app.py"
  Task: "Add CompareScreen skeleton to app.py"
  Task: "Add 'c' binding and action_compare() to CommitExplorer in app.py"
```

---

## Implementation Strategy

### MVP (User Story 1 only — Phases 1–3)

1. Phase 1: Verify environment
2. Phase 2: Add types, skeleton, binding
3. Phase 3: Implement diff/log comparison
4. **STOP and VALIDATE**: press `c`, compare two branches, confirm output
5. Merge or demo as MVP

### Incremental Delivery

1. Phases 1–3 → MVP: diff + commits view working
2. Phase 4 → add conflict detection
3. Phase 5 → add export
4. Phase 6 → polish & edge cases

---

## Notes

- All tasks modify `app.py` only (single-file architecture)
- Keep new classes/functions in logical order: Types → Backend → Screens → Helpers
- `@work` decorator required for any async operation in Textual
- Run `uv run cex owner/repo` to manually test after each phase checkpoint
- Commit after each phase checkpoint with a `feat:` conventional commit message
