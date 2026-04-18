# cex — Agent Quickstart

`cex` is a git commit explorer designed for AI agents. Every command defaults to the smallest safe output. Every capped response tells you exactly how to get more.

---

## Install

```bash
uvx commit-explorer           # run without installing
uv tool install commit-explorer  # install globally
```

---

## The Progressive Disclosure Ladder

Every command lives on one of these rungs. Start cheap; climb only as needed.

| Rung | What you get | Size | How |
|------|-------------|------|-----|
| 0 | Metadata + stat line only | ~10 lines | `--summary` |
| 1 | Metadata + file list | ~30 lines | **default** (show/compare/pr) |
| 2 | Rung 1 + diff for one file | ~50–500 lines | `--file path/to/x` |
| 3 | Rung 1 + full diff, capped | ~500 lines | `--diff` |
| 4 | Full, uncapped | unbounded | `--diff --max-lines 0` |

For list commands (`--export`, `--range`):

| Rung | What you get | Size | How |
|------|-------------|------|-----|
| 0 | Repo metadata + commit count | ~5 lines | `--summary` |
| 1 | First 50 commits + `Next:` hint | ~50 lines | **default** |
| N | Next page | ~50 lines | `--offset N` |
| * | File-history (commits touching one file) | bounded | `--file path/to/x` |

---

## Three Canonical Agent Flows

### 1. Explore a repo safely

```bash
# Start: 50 commits, bounded
cex owner/repo --export --format ndjson

# Follow the Next: hint to page
cex owner/repo --export --offset 50 --format ndjson

# Drill into one commit
cex owner/repo --show abc1234
cex owner/repo --show abc1234 --file src/backend.py
```

### 2. Trace a file's history

```bash
# Which commits touched this file?
cex owner/repo --export --file src/commit_explorer/backend.py --format ndjson

# What changed in one of those commits?
cex owner/repo --show abc1234 --file src/commit_explorer/backend.py --format json

# How did it evolve between two releases?
cex owner/repo --compare v1.0 v2.0 --file src/commit_explorer/backend.py --format json
```

### 3. Review a PR progressively

```bash
# Step 1: metadata only (~15 lines)
cex --pr https://github.com/owner/repo/pull/42 --summary --format json

# Step 2: which files changed (~30 lines)
cex --pr https://github.com/owner/repo/pull/42 --format json

# Step 3: diff for the interesting file
cex --pr https://github.com/owner/repo/pull/42 --file src/app.py --format json

# Step 4: if still unclear, full diff capped at 500 lines
cex --pr https://github.com/owner/repo/pull/42 --diff --format json
```

---

## JSON Schema Reference

### `--show` / `--compare` / `--pr` with `--format json`

```json
{
  "kind": "commit_detail",
  "repo": "owner/repo",
  "sha": "abc1234...",
  "summary": {"files": 3, "additions": 42, "deletions": 18},
  "files": [
    {"path": "src/x.py", "status": "modified", "additions": 40, "deletions": 18}
  ],
  "diff": null,
  "truncated": false,
  "next": {
    "full_diff": "cex owner/repo --show abc1234 --diff",
    "single_file": "cex owner/repo --show abc1234 --file <path>"
  }
}
```

When `truncated: true`:
```json
{
  "diff": "...first 500 lines...",
  "truncated": true,
  "total_diff_lines": 2341,
  "next": {"full_diff": "cex owner/repo --show abc1234 --diff --max-lines 0"}
}
```

### `--export` / `--range` with `--format ndjson`

One JSON object per line, then a page footer:
```
{"kind":"commit","sha":"abc1234","short_sha":"abc1234","message":"feat: ...","author":"...","date":"2024-01-15"}
{"kind":"commit",...}
{"kind":"page","shown":50,"total":1234567,"offset":0,"limit":50,"next":"cex owner/repo --export --offset 50 --limit 50"}
```

---

## Following `Next:` Hints

Every paginated or truncated response includes the exact command to continue:

```
[50 of 1,234,567 commits shown]
Next: cex torvalds/linux --export --offset 50 --limit 50
```

Run it verbatim. The hint includes all the flags from your original call (provider, depth, file filter) so you don't need to reconstruct it.

---

## Environment Variables

```bash
GITHUB_TOKEN=ghp_...      # for private GitHub repos
GITLAB_TOKEN=glpat_...    # for private GitLab repos
AZURE_DEVOPS_TOKEN=...
AZURE_DEVOPS_ORG=my-org
NO_COLOR=1                # suppress all ANSI (also auto-applied in non-TTY)
```
