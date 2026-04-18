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

## Safety Guardrails (ALWAYS follow — no exceptions without explicit user confirmation)

These rules replicate the protections of Claude Code's auto-mode classifier. They apply in every session, including `--dangerously-skip-permissions` mode.

### Reversibility Principle

Before any action, mentally classify it:
- **Reversible & local** (file edits, running tests, reading files) → proceed freely
- **Hard to reverse or affects shared state** (push, deploy, delete, permissions) → pause and confirm with the user first

When in doubt, choose the more reversible path.

---

### NEVER do without explicit user confirmation

#### Version Control
- Force push (`git push --force` or `git push -f`) to any branch
- Push directly to `main`, `master`, `production`, `release`, or any protected branch
- Rewrite or amend history on shared branches (`git rebase`, `git reset --hard` on pushed commits)
- Delete remote branches
- Create releases or tags without user verification

#### Destructive Operations
- Delete files or directories that existed before the session (`rm -rf`, `rmdir`, bulk deletes)
- Drop, truncate, or wipe database tables or collections
- Clear production caches, logs, or stateful data
- Overwrite files that were not created during this session without reading them first

#### Infrastructure & Deployment
- Deploy to production environments
- Run database migrations against production
- Modify shared infrastructure (Terraform, CloudFormation, Kubernetes manifests)
- Modify CI/CD pipeline definitions beyond what was explicitly requested

#### Secrets & Credentials
- Commit `.env`, `*.pem`, `*.key`, credential files, or any file containing secrets
- Send credentials or secret values to any external endpoint not explicitly authorized
- Log or print secret values to stdout/stderr

#### Code Execution Risks
- `curl | bash`, `wget | sh`, or any pattern that downloads and immediately executes code
- Execute scripts downloaded from untrusted or unrecognized sources
- Run inline interpreters with user-supplied code (`python -c "..."`, `node -e "..."`) unless explicitly requested

#### Permissions & Access
- Grant IAM roles, cloud permissions, or repository collaborator access
- Modify webhook configurations or security policies
- Change repository visibility (private ↔ public)

#### External Services
- Send messages on behalf of the user (Slack, email, GitHub comments, Discord, etc.)
- Write to external databases or APIs not confirmed by the user
- Upload files or data to third-party services

---

### ALLOWED by default (no confirmation needed)

- Reading any file in the working directory
- Creating and editing files in the working directory
- Running declared scripts from `package.json`, `Makefile`, or equivalent
- Installing dependencies from official registries declared in lock files
- Read-only HTTP requests (fetching docs, checking APIs)
- Normal git operations: `git add`, `git commit`, `git checkout -b <new-branch>`, `git status`, `git log`, `git diff`
- Pushing to a branch Claude created during the session
- Pushing to the current working branch (non-protected) when explicitly asked
- Creating pull requests
- Running linters, formatters, and tests

---

### Escalation Rule

A general instruction does **not** authorize specific high-risk sub-actions. Examples:
- "Clean up the repo" → does NOT authorize deleting files or branches
- "Deploy our changes" → does NOT authorize a production deploy
- "Update the config" → does NOT authorize changing CI/CD or secrets

If completing a task requires a blocked action, stop and ask the user before proceeding.

---

### On Ambiguity

If an action is ambiguous (unclear whether it's safe or matches the user's intent), default to asking rather than guessing. A short confirmation is cheaper than an unintended side effect.

## Active Technologies
- Python 3.11+ + Dulwich (git wire protocol), Textual (TUI), Rich (ANSI/markup), urllib3 (SSL proxy), python-dotenv, argparse (stdlib), json (stdlib), subprocess (git binary) (20260418-212347-agent-friendly-cli)
- N/A — no persistent state beyond temporary clone directories (20260418-212347-agent-friendly-cli)

## Recent Changes
- 20260418-212347-agent-friendly-cli: Added Python 3.11+ + Dulwich (git wire protocol), Textual (TUI), Rich (ANSI/markup), urllib3 (SSL proxy), python-dotenv, argparse (stdlib), json (stdlib), subprocess (git binary)
