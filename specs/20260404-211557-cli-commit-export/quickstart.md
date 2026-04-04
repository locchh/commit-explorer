# Quickstart: CLI Commit Export

## Export a single commit

```bash
# Export commit abc1234 from a GitHub repo to /tmp
uv run cex owner/repo --show abc1234

# Export to a custom folder (created automatically if missing)
uv run cex owner/repo --show abc1234 --out ./exports

# Short SHA or full SHA both work
uv run cex owner/repo --show f291787abc1234def5678
```

Output: one `.txt` file, path printed to stdout.  
Example filename: `20260404_abc1234_fix-null-check.txt`

---

## Export a range of commits

```bash
# All commits between two SHAs (base..target, inclusive of merge commits)
uv run cex owner/repo --range abc1234 def5678

# Last 10 commits from a SHA
uv run cex owner/repo --range def5678 --depth 10

# With custom output folder
uv run cex owner/repo --range abc1234 def5678 --out ./range-exports

# GitLab repo
uv run cex owner/repo --provider gitlab --range abc1234 def5678
```

Progress printed to stderr: `Exporting 1/10… Exporting 2/10…`  
One `.txt` file per commit, each path printed to stdout.

---

## Notes

- `REPO` (`owner/repo`) is required for both `--show` and `--range`.
- `--out` defaults to `/tmp`. The folder is created automatically.
- `--depth` controls how far back the clone fetches. For `--range base target` (2-SHA form), both SHAs must be within the cloned depth. Use no `--depth` for full history.
- For `--range sha --depth N` (1-SHA form), `--depth N` also controls how many commits are exported.
- Merge commits are included in range exports like any other commit.
- The initial commit (no parents) exports metadata with a note that no diff is available.
