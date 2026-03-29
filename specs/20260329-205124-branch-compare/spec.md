# Feature Specification: Branch Comparison View

**Feature Branch**: `20260329-205124-branch-compare`
**Created**: 2026-03-29
**Status**: Draft
**Input**: Compare two remote tracking branches before opening a PR — diff summary, unique commits, conflict detection, and export to `.txt`.

## Clarifications

### Session 2026-03-29

- Q: Where does the branch comparison live in the UI? → A: New screen/mode — pressing a key switches the whole TUI to a dedicated compare view with its own layout.
- Q: What happens when the repo was loaded with `--depth N` and the merge base is outside shallow history? → A: Show a warning banner and display partial/best-effort results.
- Q: How are the three result sections (file diff, unique commits, conflicts) arranged on the compare screen? → A: Single scrollable panel with all three sections top-to-bottom.
- Q: How does the user trigger export from the compare screen? → A: A visible "Export" button on the compare screen.
- Q: What scope of conflict detection is needed? → A: Full hunk-level — show actual conflicting lines (requires fetching blob content for conflicting files only).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare Two Remote Branches (Priority: P1)

After loading a repo, the user presses a key binding to enter compare mode. The TUI switches to a dedicated compare screen where they type two branch names (e.g., `main` and `feature/foo`). The app fetches and compares `origin/main` vs `origin/feature/foo`, showing changed files (with +/- counts), a total summary, and the commits unique to the feature branch.

**Why this priority**: The core use case — a quick pre-PR sanity check without leaving the tool.

**Independent Test**: Load a repo, press the compare key, enter two branch names, and verify the file diff and commit list match what `git diff --stat` and `git log` report.

**Acceptance Scenarios**:

1. **Given** a repo is loaded, **When** the user presses the compare key binding, **Then** the TUI switches to the compare screen with two branch-name inputs.
2. **Given** the compare screen is active and the user enters two branch names and triggers comparison, **Then** the app fetches both as `origin/*` refs and shows changed files with per-file +/- counts and a shortstat summary line.
3. **Given** the same branch is entered as both base and target, **When** comparison runs, **Then** the screen shows "no differences."
4. **Given** the remote is unreachable during fetch, **When** comparison is triggered, **Then** an error notification is shown and the inputs remain editable.

---

### User Story 2 - Detect Merge Conflicts (Priority: P2)

The compare screen flags whether merging the feature branch into the base would produce conflicts, and lists the affected files.

**Why this priority**: Conflict detection is the other half of "is this PR safe to merge?" — complements the diff view.

**Independent Test**: Use a repo where a known conflict exists; verify the conflicting file is listed. Use a clean repo; verify "no conflicts" is shown.

**Acceptance Scenarios**:

1. **Given** two branches that conflict on a file, **When** comparison runs, **Then** that file is listed under a "Conflicts" section.
2. **Given** two branches that merge cleanly, **When** comparison runs, **Then** a "clean merge" indicator is displayed.

---

### User Story 3 - Export Comparison Report (Priority: P3)

The user exports the current comparison result to a `.txt` file.

**Why this priority**: Useful for sharing async with reviewers or attaching to a PR description; non-blocking if absent.

**Independent Test**: Trigger export after a comparison and verify the output file contains the same diff summary, commit list, and conflict status shown in the compare screen.

**Acceptance Scenarios**:

1. **Given** a completed comparison, **When** the user triggers export, **Then** a `.txt` file is written and the user is notified of its path.
2. **Given** export is triggered, **Then** the filename encodes both branch names and the current date.

---

### Edge Cases

- Branch names containing `/` (e.g., `feature/my-thing`) must be handled correctly when resolving to `origin/*`.
- When the repo was loaded with `--depth N` and the merge base is outside shallow history, the compare screen MUST display a warning banner ("shallow clone: results may be incomplete") and show best-effort partial results rather than blocking or failing silently.
- Very large diffs (500+ files) should not freeze the UI.
- Export should fail gracefully if the output path is not writable.
- The user must be able to return to the main commit-explorer view from the compare screen.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The TUI MUST provide a key binding that switches from the main commit view to a dedicated compare screen.
- **FR-002**: On the compare screen, users MUST be able to type two branch short names (without `origin/` prefix) as base and target; the app resolves them to `origin/*` refs internally.
- **FR-003**: Before comparing, the tool MUST fetch to refresh all remote tracking refs.
- **FR-004**: The compare screen MUST display results in a single scrollable panel with three sections in order: (1) diff summary, (2) unique commits, (3) conflict status.
- **FR-005**: The diff summary section MUST show a per-file change list (filename, status, +/- line counts) and a total shortstat line (files changed, lines added, lines deleted).
- **FR-006**: The unique commits section MUST show the commits present in the target branch but not the base branch (short SHA, message, author, date).
- **FR-007**: The conflict status section MUST indicate whether the branches can be merged cleanly; if not, it MUST list the conflicting files and show the actual conflicting hunks (blob content for conflicting files is fetched on demand).
- **FR-008**: The compare screen MUST display a visible "Export" button; pressing it writes the comparison result (diff summary, commit log, conflict status) to a `.txt` file named with both branch names and the date.
- **FR-009**: Users MUST be able to return to the main commit-explorer view from the compare screen.

### Key Entities

- **Remote Tracking Branch**: An `origin/*` ref available after fetch; identified by its short name (e.g., `main`, `feature/foo`).
- **File Change**: A file in the diff; has filename, status (added/modified/removed/renamed), additions, deletions.
- **Unique Commit**: A commit reachable from the target but not the base; has short SHA, message, author, date.
- **Comparison Report**: The exported `.txt` containing diff summary, commit list, and conflict status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Comparison results appear in under 15 seconds for branches with up to 200 diverging commits on a standard internet connection.
- **SC-002**: File change counts and commit list match the output of the equivalent manual commands in 100% of tested cases.
- **SC-003**: Conflict detection produces zero false negatives on the repos used in testing.
- **SC-004**: Exported report contains all information shown in the compare screen, verified in 100% of test cases.

## Assumptions

- The repo is already cloned (bare, `filter=blob:none`) in the session — comparison reuses the existing clone and only fetches.
- `filter=blob:none` is sufficient for diff stats and commit log. Conflict detection requires blob content only for files that actually conflict — those blobs are fetched on demand, not for the whole repo.
- Conflict detection does not perform an actual merge; it only simulates one to identify conflicting paths.
- Comparing more than two branches at once is out of scope.
- The export file is written to the current working directory unless the user specifies otherwise.
