# CLI Flag Contract

**Feature Branch**: `20260418-212347-agent-friendly-cli`  
**Phase**: 1 — Design

This document is the authoritative specification for every flag added or changed by this feature. Changes to these flags are breaking API changes.

---

## Unchanged Flags

| Flag | Type | Default | Notes |
|------|------|---------|-------|
| `repo` | positional str | `""` | `owner/repo` format |
| `--export` | bool flag | false | Activates graph/commit-list mode |
| `--show SHA` | str | — | Single commit detail mode |
| `--compare BASE TARGET` | 2 strs | — | Branch comparison mode |
| `--pr URL` | str | — | PR/MR review mode |
| `--range SHA [SHA]` | 1–2 strs | — | Commit range mode |
| `--provider` | choice | `github` | `github` \| `gitlab` \| `azure` |
| `--depth N` | int | None | Clone depth (network optimisation) |
| `--out PATH` | str | None | Write to file; print resolved path to stdout |

---

## New Flags

### Progressive Disclosure

| Flag | Type | Default | Scope | Effect |
|------|------|---------|-------|--------|
| `--summary` | bool flag | false | all | Metadata + stat only; suppresses file list, diff, commit log |
| `--diff` | bool flag | false | `show`, `compare`, `pr` | Include full diff section; implies `--max-lines 500` unless `--max-lines` is explicit |
| `--no-diff` | bool flag | false | all | Explicitly suppress diff (wins over `--diff` if both present) |
| `--file PATH` | str, repeatable | [] | all | On `show`/`compare`/`pr`/`range`: diff for this file only; implies `--diff`. On `export`: filter commit list to commits touching PATH (rename-aware) |

### Size Caps

| Flag | Type | Default | Scope | Effect |
|------|------|---------|-------|--------|
| `--max-lines N` | int | 0 | all | Truncate stdout at N lines; `0` = unbounded. When `--diff` is used without `--max-lines`, defaults to `500` |
| `--max-bytes N` | int | 0 | all | Truncate stdout at N bytes; `0` = unbounded |

### Pagination

| Flag | Type | Default | Scope | Effect |
|------|------|---------|-------|--------|
| `--limit N` | int | 50 | `export`, `range` | Max commits per response; `0` = unbounded |
| `--offset M` | int | 0 | `export`, `range` | Skip first M commits |

### Output Format

| Flag | Type | Default | Scope | Effect |
|------|------|---------|-------|--------|
| `--format` | choice | `text` | all | `text` \| `json` \| `ndjson` |
| `--color` | choice | `auto` | all | `auto` \| `always` \| `never` |

---

## Interaction Rules

1. **`--summary` overrides everything.** When `--summary` is present, `--diff`, `--file`, `--max-lines` are all ignored for section selection (though `--max-lines` still caps total output lines).

2. **`--diff` + `--max-lines`**: If `--diff` is specified without `--max-lines`, treat as `--max-lines 500`. If `--diff` is specified with `--max-lines 0`, no cap applied. If `--diff` is not specified, `--max-lines` still applies to the overall output.

3. **`--no-diff` wins over `--diff`**: If both are present, diff is suppressed.

4. **`--file PATH` scope difference**:
   - On `export`: is a *commit* filter. Does NOT add diff to output.
   - On `show`/`compare`/`pr`/`range`: is a *diff-section* filter. Implies `--diff` for those paths.
   - Multiple `--file` flags are OR'd: commits touching *any* of the paths appear (export mode), diff for *each* path appears (show/compare/pr/range mode).

5. **`--format json`/`ndjson` forces `--color never`**: ANSI codes are never present in structured output regardless of TTY or `--color` setting.

6. **`--out PATH` + `--format json`**: JSON output goes to the file; the resolved file path is printed to stdout. These compose cleanly.

7. **`--limit 0` and `--max-lines 0`**: Both mean unbounded. Agents must explicitly opt in to unbounded output.

8. **`--offset` without `--limit`**: Valid; uses default `--limit 50`. Agent can page through with offset only.

9. **`--depth` (clone depth) is independent of `--limit`/`--offset` (view controls)**: `--depth 100` clones only 100 commits; `--limit 20 --offset 10` shows 20 of the available commits starting at position 10.

---

## Default Behaviour Change Summary (Breaking)

| Command | Old default | New default |
|---------|------------|------------|
| `--show SHA` | Writes `/tmp/YYYYMMDD_sha_slug.txt`, prints path | Stdout: metadata + file list (no diff) |
| `--compare B T` | Writes `/tmp/compare-B-T-ts.txt`, prints path | Stdout: summary + file list + commit log (no diff) |
| `--pr URL` | Writes `/tmp/compare-...-pr42-ts.txt`, prints path | Stdout: PR metadata + summary + file list + commit log (no diff) |
| `--range ...` | Writes N files to `/tmp/`, prints N paths | Stdout: per-commit metadata + file list, `---` separator |
| `--export` | Full graph, unbounded | First 50 commits + `Next:` footer |

**Migration**: Any script relying on the old `/tmp` default must add `--out /tmp` explicitly.
