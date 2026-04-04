# Data Model: CLI Commit Export by SHA and Range

## Existing types (unchanged)

### `CommitInfo` (NamedTuple)
Already defined in `app.py`. Used as the source of truth for commit metadata in all export functions.

| Field | Type | Notes |
|---|---|---|
| `sha` | `str` | Full 40-char hex SHA |
| `short_sha` | `str` | First 7 chars |
| `message` | `str` | First line of commit message |
| `author` | `str` | Display name |
| `author_email` | `str` | Email address |
| `date` | `str` | ISO 8601 timestamp |
| `parents` | `list[str]` | Full SHAs of parent commits |

### `CommitDetail` (NamedTuple)
Already defined in `app.py`. Output of `_GitBackend.get_detail(sha)`. Used directly as input to `_write_commit_export()`.

| Field | Type | Notes |
|---|---|---|
| `info` | `CommitInfo` | Commit metadata |
| `stats` | `dict[str, int]` | `{additions, deletions, total}` |
| `files` | `list[FileChange]` | Per-file change list |
| `refs` | `list[str]` | Issue refs (may be empty for CLI export) |
| `linked_prs` | `list[dict]` | Linked PRs (may be empty for CLI export) |

### `FileChange` (NamedTuple)
Already defined. Each entry in `CommitDetail.files`.

| Field | Type | Notes |
|---|---|---|
| `filename` | `str` | Relative path |
| `status` | `str` | `added`, `modified`, `removed`, `renamed` |
| `additions` | `int` | Lines added |
| `deletions` | `int` | Lines removed |

---

## New concepts (no new NamedTuples required)

### CommitExport (output artifact)
A `.txt` file on disk. Not a Python type — produced by `_write_commit_export()`.

**Filename format**: `<YYYYMMDD>_<short-sha>_<slug>.txt`  
- `<YYYYMMDD>` — date from the commit's own `date` field (not wall-clock time)
- `<short-sha>` — `CommitInfo.short_sha` (7 chars); falls back to full SHA if collision risk detected
- `<slug>` — `_slugify(CommitInfo.message)`, max 40 chars

**Example**: `20260329_f291787_add-safety-guardrails-to-claude-md.txt`

**File sections** (in order):
1. Header block — SHA, author, date, message, generated timestamp
2. `DIFF SUMMARY` — N files changed, X insertions, Y deletions
3. `CHANGED FILES (N)` — per-file status table
4. `FULL DIFF` — unified diff per file (from `difflib.unified_diff` via `get_detail`)

### CommitRange (logical concept)
The ordered list of commits returned by Dulwich `get_walker(include=[target], exclude=[base])`. Ordered newest-first (Dulwich default). Reversed to oldest-first before exporting so files sort chronologically by filename.

No NamedTuple needed — represented as `list[CommitInfo]` collected from the walker.
