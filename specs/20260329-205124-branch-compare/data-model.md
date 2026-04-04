# Data Model: Branch Comparison View

**Branch**: `20260329-205124-branch-compare` | **Date**: 2026-03-29

All types are `NamedTuple` subclasses added to `app.py`, consistent with existing types (`CommitInfo`, `FileChange`, `CommitDetail`).

## New Types

### `ConflictFile`

Represents a file with merge conflicts, including the raw conflict-marker text.

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `str` | Repo-relative path of the conflicting file |
| `conflict_text` | `str` | Raw output from merge-tree containing conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) |

### `BranchComparison`

The complete result of comparing two remote tracking branches. Passed from `_GitBackend` to `CompareScreen`.

| Field | Type | Description |
|-------|------|-------------|
| `base` | `str` | Short branch name (e.g., `main`) |
| `target` | `str` | Short branch name (e.g., `feature/foo`) |
| `stat_summary` | `str` | Raw `--shortstat` line (e.g., `3 files changed, 42 insertions(+), 5 deletions(-)`) |
| `file_changes` | `list[FileChange]` | Per-file change list (reuses existing `FileChange` type) |
| `unique_commits` | `list[CommitInfo]` | Commits in target but not base (reuses existing `CommitInfo` type) |
| `conflicts` | `list[ConflictFile]` | Conflicting files; empty list = clean merge |
| `shallow_warning` | `bool` | True if the clone is shallow and results may be incomplete |
| `full_diff` | `str` | Full `git diff --no-color` output for export |
| `full_log` | `str` | Full `git log --stat --no-color --date=iso` output for export |

### `PRMetadata`

Metadata resolved from a GitHub PR or GitLab MR URL via the provider REST API.

| Field | Type | Description |
|-------|------|-----------|
| `provider` | `str` | `"github"` or `"gitlab"` |
| `owner` | `str` | Base repo owner |
| `repo` | `str` | Base repo name |
| `number` | `int` | PR/MR number |
| `title` | `str` | PR/MR title |
| `state` | `str` | `open`, `closed`, or `merged` |
| `author` | `str` | PR/MR author username |
| `base` | `str` | Base branch name |
| `head` | `str` | Head branch name |
| `url` | `str` | Original PR/MR URL |
| `head_clone_url` | `str` | Clone URL for the head repo (may be a fork) |
| `head_owner` | `str` | Owner of the head repo (may differ from base for cross-fork PRs) |
| `description` | `str` | PR/MR body text |

## Reused Existing Types

- **`FileChange`** (`filename`, `status`, `additions`, `deletions`) — already in `app.py`; populated from `--stat` output parsing.
- **`CommitInfo`** (`sha`, `short_sha`, `message`, `author`, `author_email`, `date`, `parents`) — already in `app.py`; populated from `git log` output.

## State Transitions

```
CompareScreen idle
    │
    ▼ user submits branch names
Fetching (spinner shown)
    │
    ├─ fetch fails → error notification, return to idle
    │
    ▼ fetch succeeds
Running comparison (spinner shown)
    │
    ├─ no differences → display "no differences" message
    │
    ▼ differences found
BranchComparison result displayed
    │
    ├─ user presses Export button → .txt written, notification shown
    └─ user presses Escape → screen dismissed, return to main view

For PR/MR flow (TUI):

```
User enters PR number → _run_pr_resolve()
    │
    ▼ API call resolves base + head branch names + metadata
    ├─ cross-fork: add pr-head remote, fetch branch
    ▼ base/target inputs auto-filled → _run_comparison() triggered
    ▼ BranchComparison result displayed with PR title + description header
```
```
