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
| `build_graph(commits)` | Pure function → `list[(CommitInfo, list[str])]`; topologically sorts commits then produces Rich-markup graph lines per commit (see Graph rendering) |
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

`build_graph` topologically sorts commits (children before parents) then maintains an `active` list where `active[i]` is the SHA expected at column `i` (or `None` for a free slot). For each commit it emits up to 5 Rich-markup lines stacked in the `graph-col` label:

1. **Entry line** *(optional)* — `╷` at the commit's column when it appears as a brand-new branch tip with no visible fork origin, so the dot doesn't float disconnected
2. **Collapsed-dupes pre-line** *(optional)* — `├──╯` / `╰──┤` / `├──┼──╯` pattern when two rails carrying the same SHA converge before the node; active rails passing through the span show `┼`
3. **Node line** — bold `●` at the commit's column, `│` at other active columns
4. **Edge line** *(merge commits only)* — `├──╮` (extra parent right), `╭──┤` (extra parent left), or `╭──┼──╮` (both sides) pattern connecting to extra parent rails
5. **Continuation line** — `│` at all active columns, connects commits visually

Graph is rebuilt per page load; rails do not carry across page boundaries.

## For Debugging

When debugging graph rendering issues, use script to trace the allocation and wiring logic for a specific commit:

Example: To debug commit `7af9aa6`, set `if commit.short_sha == '7af9aa6':` in the script.

```bash
uv run python -c "
import asyncio
from app import GitHubProvider, build_graph, _topo_sort, _alloc_slot
from typing import Optional

async def main():
    gh = GitHubProvider()
    commits = await gh.fetch_all_commits('paperclipai', 'paperclip', count=60)
    commits = _topo_sort(commits)

    active: list[Optional[str]] = []
    for idx, commit in enumerate(commits):
        sha = commit.sha
        was_expected = sha in active
        try:
            col = active.index(sha)
        except ValueError:
            col = _alloc_slot(active, sha)
            active[col] = sha

        collapsed_dupes = []
        for i in range(len(active)):
            if i != col and active[i] == sha:
                collapsed_dupes.append(i)
                active[i] = None

        if commit.short_sha == '7af9aa6':
            print(f'idx={idx} col={col} was_expected={was_expected}')
            print(f'collapsed_dupes={collapsed_dupes}')
            print(f'active before wire={[s[:7] if s else None for s in active]}')
            print(f'parents={[p[:7] for p in commit.parents]}')
            break

        # wire parents
        active[col] = None
        if commit.parents:
            active[col] = commit.parents[0]
            for p in commit.parents[1:]:
                slot = _alloc_slot(active, p, prefer_near=col)
        while active and active[-1] is None:
            active.pop()

asyncio.run(main())
"
```