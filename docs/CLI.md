# CLI Reference — Commit Explorer (CEX)

`cex` has two modes: **TUI mode** (interactive terminal UI) and **headless CLI mode** (stdout-default, agent-friendly). All modes share the same flags.

---

## Synopsis

```
cex [REPO] [OPTIONS]
```

### Commands (pick one)

| Flag | Description |
|---|---|
| *(none)* | Launch interactive TUI |
| `--export` | Print the commit graph (bounded to `--limit`, default 50) |
| `--show SHA` | Emit full details of a single commit |
| `--range SHA [SHA]` | Emit a commit range — `--range BASE TARGET` or `--range TARGET --depth N` |
| `--compare BASE TARGET` | Compare two branches and emit a detailed report |
| `--pr URL` | Review a PR/MR by URL (provider inferred) |
| `--init --type TYPE` | Download skills into the current project for the chosen editor |

### Selectors & routing

| Flag | Default | Description |
|---|---|---|
| `REPO` | *(TUI prompt)* | `owner/repo` (required for headless commands except `--pr`) |
| `--provider` | `github` | `github`, `gitlab`, or `azure` |
| `--depth N` | none | Limit clone to N commits (network optimisation) |
| `--out PATH` | *stdout* | Write to files under PATH; prints resolved path(s). Directory auto-created. |

### Progressive disclosure

| Flag | Default | Description |
|---|---|---|
| `--summary` | — | Metadata + stat line only (suppresses file list and diff) |
| `--diff` | — | Include full diff; implies `--max-lines 500` unless set |
| `--no-diff` | — | Explicitly suppress the diff (wins over `--diff`) |
| `--file PATH` | — | On `--show`/`--compare`/`--pr`/`--range`: restrict diff to this file (implies `--diff`). On `--export`: filter commit list to commits that touched PATH (rename-aware). Repeatable. |

### Size caps

| Flag | Default | Description |
|---|---|---|
| `--max-lines N` | 500 when `--diff`, else 0 | Truncate stdout at N lines; 0 = unbounded |
| `--max-bytes N` | 0 | Truncate stdout at N bytes; 0 = unbounded |

### Pagination

| Flag | Default | Description |
|---|---|---|
| `--limit N` | 50 | Max commits per `--export` / `--range` response; 0 = unbounded |
| `--offset M` | 0 | Skip first M commits |

### Format & colour

| Flag | Default | Description |
|---|---|---|
| `--format {text,json,ndjson}` | `text` | Output format |
| `--color {auto,always,never}` | `auto` | Auto = TTY detection + `NO_COLOR`; forced `never` in JSON modes |

---

## Output routing contract

Every command **defaults to stdout**. All progress and chatter go to **stderr**, so stdout is safe for parsing and piping.

- **Without `--out`**: content streams directly to stdout.
- **With `--out PATH`**: one or more `.txt` files are written under PATH (created recursively if missing), and the resolved path is printed to stdout — nothing else.

This replaces the previous `/tmp`-default behaviour. Shell scripts that wrote to `/tmp` should set `--out /tmp` explicitly.

---

## Progressive disclosure ladder

Headless commands climb from cheapest → fullest. Agents should start at the top and step down only when needed:

| Rung | Flags | What you get |
|---|---|---|
| 1 | `--summary` | Metadata + diff stat line (≤ 20 lines) |
| 2 | *(default)* | Metadata + file list (no diff body) |
| 3 | `--file PATH` | Diff restricted to one file |
| 4 | `--diff` | Full diff, capped at 500 lines (truncation marker emitted) |
| 5 | `--diff --max-lines 0` | Uncapped full diff |

Priority when multiple flags are passed: `--summary` > `--no-diff` > `--diff` > `--file`.

---

## Modes

### 1. Interactive TUI (default)

Opens the terminal UI. `REPO` is optional.

```bash
cex                                   # UI, enter repo manually
cex owner/repo                        # pre-load a repo
cex owner/repo --depth 50
cex owner/repo --provider gitlab
```

**TUI keyboard shortcuts**

| Key | Action |
|---|---|
| `r` | Reload the current repo |
| `n` | Load next page of commits (30 per page) |
| `q` | Quit |
| drag divider | Resize commit list / detail panels |

---

### 2. Editor integration (`--init --type TYPE`)

Downloads `cex` skills from the GitHub repo and installs them into the current project's editor config directory.

```bash
cex --init --type claude      # → .claude/skills/
cex --init --type windsurf    # → .windsurf/skills/
cex --init --type cursor      # → .cursor/skills/
cex --init --type copilot     # → .copilot/skills/
```

Each skill is written as `<skill-name>/SKILL.md` under the target directory (created if missing). Re-running updates existing files.

`--init` requires `--type` — omitting it is an error.

---

### 3. Export graph (`--export`)

Prints a paginated commit graph to stdout.

```bash
cex owner/repo --export                            # first 50 commits + Next: hint
cex owner/repo --export --limit 20                 # smaller page
cex owner/repo --export --offset 50 --limit 50     # next page
cex owner/repo --export --limit 0                  # unbounded
cex owner/repo --export --file src/app.py          # file-history mode (rename-aware)
cex owner/repo --export --out ./artifacts          # write graph.txt into ./artifacts
```

Pagination footer (when more commits remain):

```
[50 of 2,431 commits shown]
Next: cex owner/repo --export --offset 50 --limit 50
```

File-history mode (`--file PATH`) emits a flat one-line-per-commit listing of every commit that touched PATH, following renames via `git log --follow`. The `Next:` hint preserves every `--file` flag.

---

### 4. Single commit (`--show SHA`)

```bash
cex owner/repo --show abc1234                      # file list only (no diff)
cex owner/repo --show abc1234 --summary            # metadata + stat line only
cex owner/repo --show abc1234 --diff               # full diff (capped at 500 lines)
cex owner/repo --show abc1234 --file src/app.py    # diff for that file only
cex owner/repo --show abc1234 --format json        # structured output
cex owner/repo --show abc1234 --out ./artifacts    # write file + print path
```

Short (7+ chars) and full SHAs are both accepted.

---

### 5. Commit range (`--range SHA [SHA]`)

```bash
# Form 1: all commits between two SHAs
cex owner/repo --range abc1234 def5678

# Form 2: last N commits from a SHA (requires --depth)
cex owner/repo --range def5678 --depth 10

# Section control applies per-commit
cex owner/repo --range abc1234 def5678 --summary
cex owner/repo --range abc1234 def5678 --diff --limit 5
cex owner/repo --range abc1234 def5678 --format ndjson
cex owner/repo --range abc1234 def5678 --out ./range
```

In stdout mode, entries are separated by `\n---\n`. In `--out` mode, one `.txt` per commit is written and each resolved path is printed.

---

### 6. Branch comparison (`--compare BASE TARGET`)

```bash
cex owner/repo --compare main feature/foo                         # file list, no diff
cex owner/repo --compare main feature/foo --summary               # stats only
cex owner/repo --compare main feature/foo --diff                  # full diff (capped)
cex owner/repo --compare main feature/foo --file src/auth.py      # diff for one file
cex owner/repo --compare main feature/foo --format json
cex owner/repo --compare main feature/foo --out ./reports
```

---

### 7. PR / MR review (`--pr URL`)

Resolves a GitHub PR or GitLab MR URL, clones the repo, and compares base → head. Supports cross-fork PRs.

```bash
cex --pr https://github.com/owner/repo/pull/123                   # file list
cex --pr https://github.com/owner/repo/pull/123 --summary         # metadata only
cex --pr https://github.com/owner/repo/pull/123 --diff            # full diff (capped)
cex --pr https://github.com/owner/repo/pull/123 --file src/x.py   # one file
cex --pr https://github.com/owner/repo/pull/123 --format json
cex --pr https://github.com/owner/repo/pull/123 --out ./reviews
```

The provider is inferred from the URL; `--provider` is only used as a fallback. `REPO` is optional — it is parsed from the URL.

---

## JSON / ndjson output

### `--format json`

Used with `--show`, `--compare`, `--pr`. Emits a schema-stable object with every mandatory key always present (may be `null`), snake_case keys, and no ANSI codes. Includes a `next` hints map for progressive disclosure.

```json
{
  "kind": "commit_detail",
  "repo": "owner/repo",
  "sha": "abc...",
  "summary": {"files": 3, "additions": 42, "deletions": 7},
  "files": [{"path": "src/x.py", "status": "modified", "additions": 10, "deletions": 2}],
  "diff": "diff --git a/src/x.py …",
  "truncated": false,
  "next": {
    "full_diff": "cex owner/repo --show abc... --diff --max-lines 0",
    "single_file": "cex owner/repo --show abc... --file <path>"
  }
}
```

When a diff is clipped by `--max-lines`, `truncated: true` and `total_diff_lines: N` are set.

### `--format ndjson`

Used with `--export`, `--range`. Emits one JSON object per commit on its own line, followed by a final `{"kind":"page",...}` footer with a `next` command string (or `null` when the range is exhausted).

```
{"kind":"commit","sha":"abc...","short_sha":"abc1234","message":"…","author":"…","date":"…","graph":""}
{"kind":"commit","sha":"def...","short_sha":"def5678","message":"…","author":"…","date":"…","graph":""}
{"kind":"page","shown":2,"total":2431,"offset":0,"limit":2,"next":"cex owner/repo --export --offset 2 --limit 2"}
```

Every line is individually parseable with `json.loads()`.

---

## Size caps

`--max-lines N` and `--max-bytes N` wrap stdout and silently truncate once the limit is reached, appending a single marker line:

```
… output truncated at 500 lines. Re-run with --max-lines 0 for full output.
```

Defaults:

- No `--diff` → `--max-lines 0` (unbounded, but the content itself is small)
- `--diff` (stdout) → `--max-lines 500`
- `--out PATH` → no stream truncation (files always contain full content)
- `--format json` → truncation is applied inside the diff field, not to the JSON envelope

---

## Provider authentication

Tokens are optional but strongly recommended. Copy `.env.example` to `.env`:

```env
GITHUB_TOKEN=ghp_...
GITLAB_TOKEN=glpat-...
GITLAB_URL=https://gitlab.com          # or self-hosted
AZURE_DEVOPS_TOKEN=...
AZURE_DEVOPS_ORG=myorg
GIT_SSL_NO_VERIFY=1                    # bypass SSL for corporate proxies
```

| Provider | `--provider` | `REPO` format | Auth env var |
|---|---|---|---|
| GitHub | `github` *(default)* | `owner/repo` | `GITHUB_TOKEN` |
| GitLab | `gitlab` | `owner/repo` | `GITLAB_TOKEN` |
| Azure DevOps | `azure` | `project/repo` | `AZURE_DEVOPS_TOKEN` + `AZURE_DEVOPS_ORG` |

---

## Quick examples

```bash
# Explore any public repo interactively
cex torvalds/linux

# First 50 commits, safe for agents
cex torvalds/linux --export

# Next page (follows the Next: hint verbatim)
cex torvalds/linux --export --offset 50 --limit 50

# History of one file (rename-aware)
cex torvalds/linux --export --file kernel/sched/core.c

# Single commit — progressive disclosure
cex torvalds/linux --show abc1234                 # file list
cex torvalds/linux --show abc1234 --summary       # stats only
cex torvalds/linux --show abc1234 --diff          # full diff (capped)
cex torvalds/linux --show abc1234 --file foo.c    # one file's diff

# Structured output for agents
cex torvalds/linux --show abc1234 --format json | jq .summary
cex torvalds/linux --export --format ndjson | head -50

# Compare branches
cex mygroup/myrepo --provider gitlab --compare main feature/new-auth --diff

# Review a PR before merging
cex --pr https://github.com/django/django/pull/1234 --summary

# Write reports to disk (old shell-script behaviour)
cex owner/repo --show abc1234 --out ./artifacts
cex owner/repo --compare main feature/foo --out ./reports
cex owner/repo --pr https://github.com/owner/repo/pull/42 --out ./reviews

# Bypass SSL on a corporate network
GIT_SSL_NO_VERIFY=1 cex owner/repo
```
