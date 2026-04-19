# Commit Explorer (CEX)

A terminal UI for exploring git repository history. Clones repositories directly via the git protocol (no REST API calls) and renders the commit graph exactly as `git log --graph`.

```
┌─ Toolbar ──────────────────────────────────────────────────────┐
│ [Provider ▾]  [owner/repo                    ]  [Load]         │
├─ Commit list (resizable) ──────┬──┬─ Detail ───────────────────┤
│ * feat: add login  abc1234 …   │  │ [Open in browser]          │
│ │                              │  │                            │
│ * fix: null check  def5678 …   │  │ SHA     abc1234...         │
│ ├─╮ Merge branch 'feat'        │  │ Author  Jane Doe           │
│ │ │                            │  │ Date    2026-03-10         │
│ [Load more ↓]                  │  │                            │
│                                │  │ M src/foo.py               │
└────────────────────────────────┴──┴────────────────────────────┘
```

## Quick Start

```bash
# Use in temporary
uvx --from git+https://github.com/locchh/commit-explorer cex textualize/textual

# Use as CLI tool
uv tool install git+https://github.com/locchh/commit-explorer
```

Or install with specific branch:

```bash
# Use in temporary
uvx --from git+https://github.com/locchh/commit-explorer@<branch-name> cex textualize/textual

# Use as CLI tool
uv tool install git+https://github.com/locchh/commit-explorer@<branch-name>
```

Or clone and run locally:

```bash
git clone https://github.com/locchh/commit-explorer
cd commit-explorer
uv sync
uv run cex textualize/textual
```

Or (bypass SSL for corporate proxies):

```bash
GIT_SSL_NO_VERIFY=1 uvx --from git+https://github.com/locchh/commit-explorer cex textualize/textual
```



## Usage

### Interactive TUI

```bash
uv run cex                            # open UI, enter repo manually
uv run cex owner/repo                 # pre-load a repository
uv run cex owner/repo --depth 100     # limit to last 100 commits
```

**Keyboard shortcuts:** `r` reload · `n` next page · `q` quit  
**Resize panels** by dragging the vertical divider between commit list and detail view.  
**Open in browser** — select a commit and click the button in the top-right.

### Headless CLI (stdout-default, agent-friendly)

Every headless command streams to stdout by default. Progressive-disclosure
flags (`--summary`, `--diff`, `--file`, `--max-lines`, `--format json`, …)
let you start cheap and climb to the full diff only when needed.

```bash
# Commit graph (first 50 with a Next: hint)
uv run cex owner/repo --export
uv run cex owner/repo --export --offset 50 --limit 50       # next page
uv run cex owner/repo --export --file src/app.py            # file history

# Single commit — progressive disclosure
uv run cex owner/repo --show SHA                            # file list (no diff)
uv run cex owner/repo --show SHA --summary                  # stats only
uv run cex owner/repo --show SHA --diff                     # full diff (cap 500 lines)
uv run cex owner/repo --show SHA --file src/app.py          # one file's diff

# Branch / PR comparison
uv run cex owner/repo --compare main feature/foo --diff
uv run cex --pr https://github.com/owner/repo/pull/123 --summary

# Structured output for agents
uv run cex owner/repo --show SHA --format json
uv run cex owner/repo --export --format ndjson

# Write reports to disk
uv run cex owner/repo --compare main feature/foo --out ./reports
```

See [`docs/CLI.md`](docs/CLI.md) for the full reference (every flag, pagination, JSON schema, size caps, colour control).

### Claude Code plugin

This repo ships as a Claude Code plugin that bundles a `repo-archaeology` skill — it teaches Claude Code how to drive `cex` with progressive disclosure to answer history questions about remote repos.

```
/plugin marketplace add locchh/commit-explorer
/plugin install commit-explorer@commit-explorer
```

The plugin distributes the skill only; `cex` itself must be installed separately (`uv tool install git+https://github.com/locchh/commit-explorer`) since plugins can't ship native binaries.

## How it works

1. **Clone** — uses [Dulwich](https://www.dulwich.io/) to bare-clone the repository with `filter=blob:none` (commits and trees only, no file contents). Fast even for large repos.
2. **Graph** — runs `git log --graph --color=always` on the local clone. The output is parsed into colored [Rich](https://github.com/Textualize/rich) `Text` objects for display in the TUI.
3. **Detail** — file changes are computed via Dulwich tree diffs on demand when a commit is selected.

Requires `git` to be installed on the system (used for graph rendering only).

## Providers

Select the provider from the dropdown, then enter `owner/repo` and press Load.

| Provider | Input format | Auth env var |
|---|---|---|
| GitHub | `owner/repo` | `GITHUB_TOKEN` |
| GitLab | `owner/repo` | `GITLAB_TOKEN` |
| Azure DevOps | `project/repo` | `AZURE_DEVOPS_TOKEN`, `AZURE_DEVOPS_ORG` |

Tokens are optional but recommended to avoid rate limits on clone URLs. Copy `.env.example` to `.env` and fill in your tokens:

```bash
cp .env.example .env
```

### Self-hosted GitLab

Set `GITLAB_URL` in `.env` to your instance URL:

```env
GITLAB_URL=https://gitlab.mycompany.com
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- `git` (system install)

## Related

- [Dulwich](https://www.dulwich.io/) — pure-Python git implementation used for cloning
- [Textual](https://textual.textualize.io/) — TUI framework
- [Rich](https://github.com/Textualize/rich) — text formatting and ANSI parsing
- [urllib3](https://urllib3.readthedocs.io/en/stable/) — HTTP client used for API requests

## License

MIT
