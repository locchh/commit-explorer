# Quickstart: Branch Comparison View

## Using the Compare Screen

1. Load a repository as normal (`owner/repo` + Load).
2. Press `c` to open the compare screen.
3. In the **Base branch** input, type the branch name (e.g., `main`).
4. In the **Target branch** input, type the branch name (e.g., `feature/my-thing`).
5. Press Enter or click **Compare**.
6. The screen fetches remote refs and displays a scrollable result panel:
   - **Diff Summary** — total files/lines changed, per-file breakdown
   - **Commits** — commits in target not in base
   - **Conflicts** — conflicting files with hunk detail, or "Clean merge"
7. Press **Export** to save the result to a `.txt` file in your working directory.
8. Press `Escape` to return to the main commit view.

## Notes

- If the repo was loaded with `--depth N`, a shallow-clone warning may appear and some results may be incomplete.
- Branch names with `/` (e.g., `feature/foo`) are supported — type them as-is without the `origin/` prefix.
- The compare screen reuses the existing clone; no re-download occurs.

## Development Setup

```bash
uv sync
uv run cex owner/repo   # load a repo, then press 'c'
```
