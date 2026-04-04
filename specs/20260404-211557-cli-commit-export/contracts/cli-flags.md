# CLI Contract: New Flags

## New flags added to `main()` argparse

### `--show <sha>`

| Property | Value |
|---|---|
| Argument name | `--show` |
| Metavar | `SHA` |
| Type | `str` |
| Required | No (only active when present) |
| Conflicts | Cannot be combined with `--compare`, `--export`, or `--pr` |
| Help text | `Export full details of a single commit to a .txt file` |

**Behaviour**: Clones `REPO` (required), resolves `SHA` via Dulwich, calls `get_detail(sha)`, writes one `.txt` file to `--out` folder, prints file path to stdout, exits.

---

### `--range [<base-sha>] <target-sha>`

| Property | Value |
|---|---|
| Argument name | `--range` |
| Nargs | `'+'` (1 or 2 values) |
| Metavar | `SHA` |
| Required | No |
| Conflicts | Cannot be combined with `--show`, `--compare`, `--export`, or `--pr` |
| Help text | `Export a linear commit range. --range TARGET [--depth N] or --range BASE TARGET` |

**1-SHA form** (`--range <target> --depth N`):  
Walk N ancestors of `<target>`, export each. `--depth` controls both clone depth and export count.

**2-SHA form** (`--range <base> <target>`):  
Export all commits in `<base>..<target>` (Dulwich `get_walker(include=[target], exclude=[base])`), merge commits included.

Progress printed to stderr: `Exporting N/total…` per commit.  
Each file path printed to stdout on completion.

---

### `--out <folder>`

| Property | Value |
|---|---|
| Argument name | `--out` |
| Metavar | `PATH` |
| Type | `str` |
| Default | `/tmp` |
| Required | No |
| Applies to | `--show`, `--range`, `--compare`, `--pr` |
| Help text | `Output folder for exported .txt files (default: /tmp, created if missing)` |

**Behaviour**: Folder is created with `os.makedirs(out_dir, exist_ok=True)` in `main()` before any headless function is called. In TUI mode (no headless flag), `--out` is a no-op.

---

## Modified existing flags

### `--depth N`

Existing flag. Gains dual meaning when used with `--range <sha>`:  
- Controls clone depth (as before)  
- Controls number of commits exported in the 1-SHA range form

No change to argument definition; documented in help text update.

---

## Dispatch table (updated `main()` logic)

```
if args.pr      → _pr_review(url, provider, depth, out_dir)
elif args.show  → _show(owner, repo, provider, sha, depth, out_dir)
elif args.range → _range(owner, repo, provider, range_shas, depth, out_dir)
elif args.compare → _compare(owner, repo, provider, depth, base, target, out_dir)
elif args.export  → _export(owner, repo, provider, depth)   # stdout only, --out N/A
else            → CommitExplorer(...).run()
```

---

## Output filename contract

Pattern: `<YYYYMMDD>_<short-sha>_<slug>.txt`

| Segment | Source | Max length |
|---|---|---|
| `YYYYMMDD` | Commit date (`CommitInfo.date[:10].replace("-","")`) | 8 |
| `short-sha` | `CommitInfo.short_sha` (7 chars) | 7 |
| `slug` | `_slugify(CommitInfo.message)` | 40 |

Separator: `_` between segments.  
Slug rules: lowercase, non-alphanumeric runs → `-`, stripped, max 40 chars.

**Example**: `20260329_f291787_add-safety-guardrails-to-claude-md.txt`
