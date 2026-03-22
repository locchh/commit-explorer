# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run cex [owner/repo] [--depth N] [--export]

# Examples
uv run cex                          # Interactive mode
uv run cex torvalds/linux --depth 100
uv run cex owner/repo --export     # Print graph to stdout
```

## Architecture

The entire application lives in a single file: `app.py` (~890 lines).

### Layers

1. **Git Providers** (`GitHubProvider`, `GitLabProvider`, `AzureDevOpsProvider`) — subclasses of `GitProvider` ABC. Each builds authenticated clone URLs and browser commit URLs from environment tokens.

2. **`_GitBackend`** — manages git operations via Dulwich (pure-Python git):
   - `load(url, depth)` — bare-clones with `filter=blob:none` (no blobs, just commits+trees) into a temp dir
   - `_extract_commits()` — walks the DAG, returns `CommitInfo` namedtuples
   - `get_detail(sha)` — on-demand: computes file diffs using `tree_changes()` + `difflib.unified_diff()`
   - Pagination: 30 commits per page

3. **`_build_graph_from_git()`** — renders the commit graph by running `git log --graph --color=always` as a subprocess. Uses `\x01`/`\x00` markers to parse commit lines vs. graph decoration lines without regex. Converts ANSI colors to Rich `Text` objects.

4. **Textual UI** — `CommitExplorer(App)` is the root. Key widgets:
   - `CommitItem(ListItem)` — one row per commit (graph line + metadata)
   - `Splitter` / `GraphSplitter` — draggable dividers for resizing panels
   - Background work via Textual's `@work` decorator; spinner shown during clone/fetch

### Data Flow

```
User input (owner/repo + provider)
  → _fetch_commits() [@work, async]
    → GitProvider builds URL
    → _GitBackend.load() clones repo
    → _build_graph_from_git() renders graph
    → ListView populated (30 at a time)
  → User selects commit
    → _fetch_detail() [@work, async]
      → _GitBackend.get_detail(sha)
      → Detail panel updates
```

### Core Types (NamedTuples)

- `CommitInfo` — sha, short_sha, message, author, author_email, date, parents
- `FileChange` — filename, status, additions, deletions
- `CommitDetail` — info, stats, files, refs, linked_prs
- `RepoInfo` — description, default_branch, language, stars, forks, branches, total_commits

## Environment Variables

Copy `.env.example` to `.env` for provider authentication:

```bash
GITHUB_TOKEN=...
GITLAB_TOKEN=...
GITLAB_URL=https://gitlab.com   # or custom self-hosted
AZURE_DEVOPS_TOKEN=...
AZURE_DEVOPS_ORG=...
GIT_SSL_NO_VERIFY=1             # bypass SSL cert verification (corporate proxies)
```

## Key Behaviors

- **Shallow clone optimization**: Uses `filter=blob:none` — file content is never fetched, only commits and trees. This makes large repos fast to load.
- **SSL bypass**: When `GIT_SSL_NO_VERIFY=1` is set, a custom `urllib3.PoolManager` with `cert_reqs=ssl.CERT_NONE` is passed to Dulwich's `porcelain.clone()`.
- **Graph rendering**: Avoids custom graph.c port — delegates entirely to subprocess `git log --graph`. NUL-delimited markers extract structured fields without regex parsing.
