# Data Model: Agent-Friendly CLI

**Feature Branch**: `20260418-212347-agent-friendly-cli`  
**Phase**: 1 — Design

---

## Existing Domain Entities (unchanged)

These types are defined in `src/commit_explorer/models.py` and are not modified by this feature.

| Entity | Key Fields | Notes |
|--------|-----------|-------|
| `CommitInfo` | sha, short_sha, message, author, author_email, date, parents | Core commit identity |
| `FileChange` | filename, status, additions, deletions | One changed file within a commit |
| `CommitDetail` | info, stats, files, refs, linked_prs | Full commit view |
| `BranchComparison` | base, target, stat_summary, file_changes, unique_commits, conflicts, full_diff, full_log, shallow_warning | Compare / PR result |
| `PRMetadata` | provider, owner, repo, number, title, state, author, base, head, url, head_clone_url, head_owner, description | PR/MR metadata |
| `RepoInfo` | description, default_branch, language, stars, forks, branches, total_commits | Repository metadata |

---

## New Type: `OutputConfig`

**Location**: `src/commit_explorer/format.py` (introduced in Phase 5; referenced by handlers from Phase 1 onward via a simple dataclass definition in `cli.py` until Phase 5 promotes it)

**Purpose**: Bundles all output-shaping options that cut across commands. Assembled once in `main()` from parsed args; passed into every command handler; handlers pass relevant fields to writers.

```python
@dataclasses.dataclass
class OutputConfig:
    # Destination
    stream: IO[str] | None = None   # None → write to file; set → write to this stream
    out_dir: str | None = None      # None → use stream

    # Section control
    include_diff: bool = False      # --diff enables; default off
    include_files: bool = True      # --summary disables
    file_filter: list[str] = field(default_factory=list)  # empty → no filter

    # Size caps
    max_lines: int = 0              # 0 = unbounded; auto-set to 500 when include_diff=True
    max_bytes: int = 0              # 0 = unbounded

    # Pagination
    limit: int = 50                 # 0 = unbounded; default 50 for export/range
    offset: int = 0

    # Format & colour
    fmt: str = "text"               # "text" | "json" | "ndjson"
    color: str = "auto"             # "auto" | "always" | "never"
```

**Invariants**:
- `stream` and `out_dir` are mutually exclusive. If `out_dir` is set, `stream` is ignored.
- When `include_diff=True` and `max_lines=0`, set `max_lines=500` at construction time.
- When `fmt` is `"json"` or `"ndjson"`, `color` is forced to `"never"` regardless of user input.
- `file_filter` on `--export` is a commit-selection filter; on `--show`/`--compare`/`--pr`/`--range` it is a diff-section filter and implies `include_diff=True`.

---

## New Type: `PageInfo`

**Location**: Returned inline from paginated writers; not persisted.

**Purpose**: Carries the pagination footer data emitted at the end of every `--export`/`--range` response.

```python
@dataclasses.dataclass
class PageInfo:
    shown: int       # commits in this response
    total: int       # total matching commits
    offset: int      # offset used for this page
    limit: int       # limit used for this page
    next_cmd: str | None  # None if this is the last page
```

**Text rendering**:
```
[50 of 1,234,567 commits shown]
Next: cex owner/repo --export --offset 50 --limit 50
```

**JSON rendering** (final line in ndjson, or top-level field in json):
```json
{"kind": "page", "shown": 50, "total": 1234567, "next": "cex ... --offset 50"}
```

---

## JSON Output Schema

### Single-object commands (`--show`, `--compare`, `--pr`) with `--format json`

```json
{
  "kind": "commit_detail" | "branch_comparison" | "pr_review",
  "repo": "owner/repo",

  // commit_detail only
  "sha": "abc1234...",

  // branch_comparison / pr_review only
  "base": "main",
  "target": "feature-x",

  // pr_review only
  "pr": {
    "number": 42,
    "title": "...",
    "state": "open" | "merged" | "closed",
    "author": "...",
    "body": "..."
  },

  "summary": {
    "files": 3,
    "additions": 42,
    "deletions": 18
  },

  // null when include_files=False (--summary flag)
  "files": [
    {"path": "src/x.py", "status": "modified", "additions": 40, "deletions": 18}
  ],

  // null when include_diff=False (default)
  "diff": "...",

  "truncated": false,

  // present only when truncated=true
  "total_diff_lines": 2341,

  // always present; null if no more data available
  "next": {
    "full_diff": "cex owner/repo --show abc1234 --diff --max-lines 0",
    "single_file": "cex owner/repo --show abc1234 --file <path>"
  }
}
```

### List-shaped commands (`--export`, `--range`) with `--format ndjson`

One JSON object per line:
```json
{"kind": "commit", "sha": "abc1234", "short_sha": "abc1234", "message": "feat: ...", "author": "...", "date": "2024-01-15", "graph": "* |"}
```

Final line (page footer):
```json
{"kind": "page", "shown": 50, "total": 1234567, "offset": 0, "limit": 50, "next": "cex owner/repo --export --offset 50 --limit 50"}
```

### Schema stability contract

- All mandatory keys are always present (never absent, may be `null`).
- `kind` is always the first key.
- Key names are `snake_case` and will not be renamed across versions without a MAJOR version bump.
- No ANSI colour codes ever appear in JSON/ndjson output.

---

## State Transitions

`OutputConfig.include_diff` follows this priority order (later rules win):

```
default: False
↓ --diff flag → True
↓ --no-diff flag → False
↓ --file PATH specified (on show/compare/pr/range) → True (for those files only)
↓ --summary flag → include_diff=False, include_files=False (overrides all)
```
