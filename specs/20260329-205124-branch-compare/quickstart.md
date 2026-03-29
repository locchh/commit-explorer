# Quickstart: Branch Comparison View

## TUI — Compare Two Branches

1. Load a repository as normal (`owner/repo` + Load).
2. Press `c` to open the compare screen.
3. In the **Base branch** input, type the branch name (e.g., `main`).
4. In the **Target branch** input, type the branch name (e.g., `feature/my-thing`).
5. Press Enter or click **Compare**.
6. The screen fetches remote refs and displays a scrollable result panel:
   - **Diff Summary** — total files/lines changed, per-file breakdown
   - **Commits** — commits in target not in base
   - **Conflicts** — conflicting files listed, or "Clean merge"
7. Press **Export** to save a detailed `.txt` report to your working directory.
8. Press `Escape` to return to the main commit view.

## TUI — Review a PR/MR

1. Load the repository the PR targets.
2. Press `c` to open the compare screen.
3. In the **PR/MR number** input, type the PR number (e.g., `123`) — or paste a full URL.
4. Press Enter or click **Fill branches** — base and target inputs auto-fill from the API.
5. Comparison runs automatically; PR title and description appear at the top of results.
6. Press **Export** to save the report (filename includes the PR number).

## CLI — Compare Branches

```bash
uv run cex owner/repo --compare main feature/foo
```

Prints a summary to stdout and writes `compare-main-feature-foo-YYYYMMDD.txt`.

## CLI — Review a PR/MR

```bash
uv run cex --pr https://github.com/owner/repo/pull/123
```

Resolves base/head from the GitHub/GitLab API, clones, compares, and writes
`compare-owner-repo-pr123-YYYYMMDD.txt` with a PR metadata header.

## Notes

- Branch names with `/` (e.g., `feature/foo`) are supported — type as-is without `origin/` prefix.
- Cross-fork PRs are handled: the fork is added as a `pr-head` remote automatically.
- Export includes full `git diff` patch and `git log --stat` output.
- Set `GITHUB_TOKEN` / `GITLAB_TOKEN` env vars to avoid API rate limits.

## Development Setup

```bash
uv sync
uv run cex owner/repo   # load a repo, then press 'c'
```
