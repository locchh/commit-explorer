# Research: CLI Commit Export by SHA and Range

## Decision 1 — Short SHA Resolution in Dulwich

**Decision**: Use `repo.object_store[sha_hex.encode()]` directly; Dulwich's `DiskObjectStore` supports prefix matching for short hex strings (≥4 chars). Wrap in `KeyError` catch to detect invalid/ambiguous SHAs.

**Rationale**: Existing `get_detail(sha)` already calls `repo[sha.encode()]`, which delegates to the object store. The same lookup works for short SHAs via Dulwich's internal prefix scan. No external resolution needed.

**Alternatives considered**:
- Running `git rev-parse <sha>` as a subprocess — adds a process spawn per lookup; rejected (complexity, no gain).
- Iterating all objects in the store — O(n) scan, rejected in favor of Dulwich's built-in prefix lookup.

---

## Decision 2 — Range Walk (`base..target`) in Dulwich

**Decision**: Use `repo.get_walker(include=[target_sha_bytes], exclude=[base_sha_bytes])` from `dulwich.walk`. This is the exact Dulwich equivalent of `git log base..target`.

**Rationale**: `_extract_commits()` already uses `repo.get_walker(include=[...])`. Adding `exclude=[base_sha_bytes]` gives the range walk for free. The walker returns `WalkEntry` objects; `.commit` gives the `Commit` object.

**For single-SHA + depth N form**: Use `repo.get_walker(include=[sha_bytes], max_entries=N)`.

**Alternatives considered**:
- Running `git log --format=%H base..target` as subprocess — works but adds shell dependency beyond what's constitutionally required; rejected.
- Manual parent traversal — reimplements what Dulwich already does; rejected.

---

## Decision 3 — Per-Commit Export Format

**Decision**: New `_write_commit_export(detail: CommitDetail, out_dir: str) -> str` function. File format mirrors the existing `_write_export` style (separator lines, section headers), adapted for a single commit:

```
========================================================================
Commit:   <full sha>
Author:   <author> <email>
Date:     <ISO date>
Message:  <first line of message>
Generated: <timestamp>
========================================================================

DIFF SUMMARY
------------------------------------------------------------------------
<N files changed, X insertions, Y deletions>

CHANGED FILES (N)
------------------------------------------------------------------------
  MODIFIED   path/to/file.py   +12  -3
  ...

FULL DIFF
------------------------------------------------------------------------
<per-file unified diff>
```

**Filename format** (from clarification): `<date>_<short-sha>_<slug>.txt`  
Example: `20260404_abc1234_fix-null-check.txt`

**Rationale**: Consistent look with existing `--compare`/`--pr` exports. Users piping both into the same folder get visually uniform files.

**Alternatives considered**:
- JSON format — machine-readable but not user-friendly; out of scope.
- Reusing `BranchComparison` / `_write_export` — wrong shape (designed for two-branch diff); rejected.

---

## Decision 4 — `--out` Flag Retrofit to Existing Modes

**Decision**: Add `out_dir: str = "."` parameter to `_write_export()`. Update `_compare()` and `_pr_review()` to pass `out_dir` through. `main()` creates the folder with `os.makedirs(out_dir, exist_ok=True)` before dispatching to any headless function.

**Rationale**: Single `makedirs` call in `main()` means none of the headless functions need to handle folder creation themselves. Centralised, DRY.

**Alternatives considered**:
- Each function creates its own folder — duplicated logic; rejected.

---

## Decision 5 — Slug Generation

**Decision**: Simple inline helper `_slugify(text: str) -> str`:
1. Lowercase
2. Replace any non-alphanumeric run with `-`
3. Strip leading/trailing `-`
4. Truncate to 40 characters

**Rationale**: stdlib-only (`re.sub`). No new dependency. 40-char limit keeps filenames readable without hitting OS path-length limits.

**Alternatives considered**:
- `python-slugify` package — unnecessary dependency for a 3-line function; rejected.
