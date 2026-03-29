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
uvx --from git+https://github.com/locchh/commit-explorer@20260329-205124-branch-compare cex textualize/textual

# Use as CLI tool
uv tool install git+https://github.com/locchh/commit-explorer@20260329-205124-branch-compare
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

```bash
uv run cex                                        # open the UI, enter repo manually
uv run cex owner/repo                             # pre-load a repository
uv run cex owner/repo --depth 100                 # limit to last 100 commits
uv run cex owner/repo --export                    # print graph to stdout and exit
uv run cex owner/repo --compare main feature/foo  # compare two branches, write report to .txt
```

**Keyboard shortcuts:** `r` reload · `n` next page · `q` quit

**Resize panels** by dragging the vertical divider between the commit list and detail view.

**Open in browser** — select a commit and click the button in the top-right to open it on the provider's website.

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
