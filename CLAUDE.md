# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for dependency management with a `.venv` at the project root.

```bash
# Run the app
uv run python app.py
uv run python app.py owner/repo   # pre-load a repository

# Install dependencies
uv sync
```

There are no tests or linting configured.

## Architecture

The entire application lives in a single file: `app.py`.

**Stack:** [Textual](https://textual.textualize.io/) TUI framework + `httpx` for async HTTP + provider REST APIs.

### Layout

```
┌─ Toolbar ──────────────────────────────────────────────┐
│ [Provider ▾]  [owner/repo input          ]  [Load]     │
├─ #left (resizable) ──┬─ Splitter ─┬─ #right ───────────┤
│ ListView of          │            │ [Open in browser]   │
│ CommitItem widgets   │  drag to   │                     │
│ (paginated, 30/page) │  resize    │ Commit detail:      │
│                      │            │ stats, files,       │
│ [Load more ↓]        │            │ linked PRs          │
└──────────────────────┴────────────┴─────────────────────┘
```

- **Left panel** (`#left`): `ListView` of `CommitItem` widgets with a git-graph column and commit info column side by side. Width is adjustable by dragging the `Splitter`.
- **Right panel** (`#right`): "Open in browser" button (enabled once a commit is loaded) + scrollable `Static` detail view.

### Key classes

| Class / function | Role |
|---|---|
| `CommitExplorer(App)` | Main Textual app; holds `_page`, `_owner`, `_repo`, `_current_sha` |
| `CommitItem(ListItem)` | Renders one commit row: colored graph column + bold message + sha/date/author |
| `Splitter(Widget)` | Draggable 1-char-wide divider; adjusts `#left` width via mouse capture |
| `build_graph(commits)` | Pure function → `list[(CommitInfo, list[str])]`; produces Rich-markup graph lines (node + optional edge + continuation) |
| `_fetch_commits(replace)` | `@work` async worker; fetches paginated commits, rebuilds graph, appends/replaces `ListView` |
| `_fetch_detail(sha)` | `@work` async worker; fetches full commit detail + linked PRs, enables "Open in browser" button |
| `GitProvider` (ABC) | Interface: `fetch_commits`, `fetch_detail`, `commit_url`, `name` |

### Providers

Three providers implement `GitProvider`:

| Provider | Env vars |
|---|---|
| `GitHubProvider` | `GITHUB_TOKEN` |
| `GitLabProvider` | `GITLAB_TOKEN`, `GITLAB_URL` (base URL, defaults to `https://gitlab.com`) |
| `AzureDevOpsProvider` | `AZURE_DEVOPS_TOKEN`, `AZURE_DEVOPS_ORG` |

`GITLAB_URL` accepts either a bare host (`https://gitlab.mycompany.com`) or a full API URL (`https://gitlab.mycompany.com/api/v4`).

Each provider implements `commit_url(owner, repo, sha)` which returns the browser URL opened by the "Open in browser" button:
- **GitHub**: `github.com/{owner}/{repo}/commit/{sha}`
- **GitLab** (including self-hosted): `{host}/{owner}/{repo}/-/commit/{sha}`
- **Azure DevOps**: `dev.azure.com/{org}/{project}/_git/{repo}/commit/{sha}`

### Graph rendering

`build_graph` maintains an `active` list where `active[i]` is the SHA expected at column `i` (or `None` for a free slot). For each commit it emits up to 3 Rich-markup lines stacked in the `graph-col` label:

1. **Node line** — bold `●` at the commit's column, `│` at other active columns
2. **Edge line** (merge commits only) — `├─╮` / `╭─┤` pattern showing the fork to extra parent rails
3. **Continuation line** — `│` at all active columns, connects commits visually

Graph is rebuilt per page load; rails do not carry across page boundaries.
