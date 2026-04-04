# CLI Reference — Commit Explorer (CEX)

`cex` has two modes: **TUI mode** (interactive terminal UI) and **headless CLI mode** (no UI, output to stdout/file). All modes share the same flags.

---

## Synopsis

```
cex [REPO] [OPTIONS]
```

| Argument / Flag | Description |
|---|---|
| `REPO` | Repository in `owner/repo` format (optional in TUI mode) |
| `--provider` | Git provider: `github` (default), `gitlab`, `azure` |
| `--depth N` | Limit fetch to N most-recent commits |
| `--export` | Print commit graph to stdout and exit (no TUI) |
| `--compare BASE TARGET` | Compare two branches, write report to `.txt` |
| `--pr URL` | Review a PR/MR by URL, write report to `.txt` |

---

## Modes

### 1. Interactive TUI (default)

Opens the terminal UI. `REPO` is optional — you can type a repo into the input bar after launch.

```bash
cex                                   # launch UI, enter repo manually
cex owner/repo                        # pre-load a repo on startup
cex owner/repo --depth 50             # pre-load, limit to last 50 commits
cex owner/repo --provider gitlab      # pre-load from GitLab
```

**TUI keyboard shortcuts**

| Key | Action |
|---|---|
| `r` | Reload the current repo |
| `n` | Load next page of commits (30 per page) |
| `q` | Quit |
| drag divider | Resize commit list / detail panels |

---

### 2. Export graph (`--export`)

Prints the colored commit graph to stdout and exits. Useful for piping into other tools or saving to a file.

```bash
cex owner/repo --export
cex owner/repo --export --depth 100
cex owner/repo --export --provider gitlab
cex owner/repo --export > graph.txt    # save to file (ANSI stripped by shell redirect)
```

Output format (one line per commit):
```
* <graph>  <short-sha>  <commit message>  <author>, <date>
```

> `REPO` is required for this mode.

---

### 3. Branch comparison (`--compare BASE TARGET`)

Compares two branches. Prints a summary to stdout and writes a detailed report to a timestamped `.txt` file in the current directory.

```bash
cex owner/repo --compare main feature/foo
cex owner/repo --compare main feature/foo --depth 200
cex owner/repo --compare main feature/foo --provider gitlab
cex owner/repo --compare develop release/1.0 --provider azure
```

**stdout summary includes:**
- Diffstat (files changed, insertions, deletions)
- Per-file change table (`M`/`A`/`D`, `+additions`, `-deletions`)
- Number of unique commits in TARGET not in BASE
- Conflict detection (`⚠ N conflict(s)` or `✓ Clean merge`)

**Exported `.txt` file includes:**
- Full diff per file
- Commit log of unique commits
- Conflict markers if any

> `REPO` and both branch names are required. Provider is inferred from `--provider` (default: `github`).

---

### 4. PR / MR review (`--pr URL`)

Resolves a GitHub PR or GitLab MR URL, clones the repository, compares the base and head branches, and writes a report. Supports **cross-fork PRs** (head branch from a fork).

```bash
cex --pr https://github.com/owner/repo/pull/123
cex --pr https://gitlab.com/owner/repo/-/merge_requests/45
cex --pr https://github.com/owner/repo/pull/123 --depth 50
```

The provider is **inferred from the URL** — the `--provider` flag is only used as a fallback.

**stdout summary includes:**
- PR/MR number, title, state, and author
- Base → head branch names
- Diffstat + per-file table
- Unique commits in the head branch
- Conflict detection

**Exported `.txt` file includes:**
- PR metadata header
- Full diff
- Commit log

> `REPO` is optional — it is inferred from the URL automatically.

---

## Provider authentication

Tokens are optional but strongly recommended to avoid rate limits on clone URLs. Set them in `.env` (copy from `.env.example`):

```env
GITHUB_TOKEN=ghp_...
GITLAB_TOKEN=glpat-...
GITLAB_URL=https://gitlab.com          # or self-hosted URL
AZURE_DEVOPS_TOKEN=...
AZURE_DEVOPS_ORG=myorg
GIT_SSL_NO_VERIFY=1                    # bypass SSL for corporate proxies
```

| Provider | `--provider` value | `REPO` format | Auth env var |
|---|---|---|---|
| GitHub | `github` (default) | `owner/repo` | `GITHUB_TOKEN` |
| GitLab | `gitlab` | `owner/repo` | `GITLAB_TOKEN` |
| Azure DevOps | `azure` | `project/repo` | `AZURE_DEVOPS_TOKEN` + `AZURE_DEVOPS_ORG` |

---

## Output files

`--compare` and `--pr` both write a `.txt` report to the **current working directory**.

Filename format:
```
<repo>_<base>_vs_<target>_<timestamp>.txt
# e.g. commit-explorer_main_vs_feature-foo_20260404-153012.txt
```

The timestamp prevents overwrites when running the same comparison multiple times.

---

## Quick examples

```bash
# Explore any public repo interactively
cex torvalds/linux

# Fast graph of last 50 commits, no UI
cex torvalds/linux --export --depth 50

# Compare two branches on a private GitLab repo
cex mygroup/myrepo --provider gitlab --compare main feature/new-auth

# Review a PR before merging (cross-fork supported)
cex --pr https://github.com/django/django/pull/1234

# Bypass SSL on a corporate network
GIT_SSL_NO_VERIFY=1 cex owner/repo
```
