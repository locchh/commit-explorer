# Commit Explorer

A terminal UI for exploring git repository history across GitHub, GitLab, and Azure DevOps.

```
┌─ Toolbar ──────────────────────────────────────────────┐
│ [Provider ▾]  [owner/repo input          ]  [Load]     │
├─ Commit list (resizable) ──┬──┬─ Detail ───────────────┤
│ ● feat: add login          │  │ [Open in browser]      │
│ │                          │  │                        │
│ ● fix: null check          │  │ SHA     abc1234...     │
│ │                          │  │ Author  Jane Doe       │
│ ├─╮ Merge branch 'feat'    │  │ Stats   +12  -3        │
│ │ │                        │  │                        │
│ [Load more ↓]              │  │ Files changed...       │
└────────────────────────────┴──┴────────────────────────┘
```

## Quick Start
The app can be run directly from GitHub with this command:

```bash
uvx --from git+https://github.com/locchh/commit-explorer commit-explorer
```

Or with a specific repository pre-loaded:

```bash
uvx --from git+https://github.com/locchh/commit-explorer commit-explorer textualize/textual
```

## Setup

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
cp .env.example .env
# edit .env and add your tokens
```

## Usage

```bash
uv run commit-explorer                      # open the UI
uv run commit-explorer textualize/textual    # pre-load a repository
```

**Keyboard shortcuts:** `r` reload, `n` next page, `q` quit.

**Resize panels** by clicking and dragging the vertical divider between the commit list and detail view.

**Open in browser** — select any commit; the button in the top-right becomes active and opens the commit page in your browser.

## Providers

Select the provider from the dropdown in the toolbar, then enter `owner/repo` and press Load.

| Provider | Input format | Required env vars |
|---|---|---|
| GitHub | `owner/repo` | `GITHUB_TOKEN` |
| GitLab | `owner/repo` | `GITLAB_TOKEN` |
| Azure DevOps | `project/repo` | `AZURE_DEVOPS_TOKEN`, `AZURE_DEVOPS_ORG` |

### Self-hosted GitLab

Set `GITLAB_URL` in `.env` to your instance (bare host or full API URL):

```env
GITLAB_URL=https://gitlab.mycompany.com
```

## Environment variables

See `.env.example` for all variables. Tokens are optional but strongly recommended to avoid API rate limits.

## Related to

- [Git](https://github.com/git/git.git) - Git
- [Textualize](https://github.com/Textualize) - The organization behind Textual and Rich
- [Textual](https://textual.textualize.io/) - The UI framework used
- [Rich](https://github.com/Textualize/rich) - The text formatting library used
- [httpx](https://www.python-httpx.org/) - The HTTP client library used

## License

MIT
