# Research: Branch Comparison View

**Branch**: `20260329-205124-branch-compare` | **Date**: 2026-03-29

## 1. Textual Screen Navigation

**Decision**: Use Textual's `Screen` class with `app.push_screen()` / `screen.dismiss()`.

**Rationale**: `push_screen` preserves the main app state on a stack. Pressing the compare key pushes `CompareScreen`; pressing the back key calls `self.dismiss()` which pops it and returns to `CommitExplorer`. This avoids re-cloning or re-loading the repo.

**Pattern**:
```python
class CompareScreen(Screen):
    BINDINGS = [Binding("escape", "dismiss", "Back")]
    ...

# In CommitExplorer:
BINDINGS = [..., Binding("c", "compare", "Compare branches")]

def action_compare(self) -> None:
    self.push_screen(CompareScreen(self._backend, self.current_provider, self._owner, self._repo))
```

**Alternatives considered**: `switch_screen` (replaces stack, loses main state — rejected), separate App instance (violates single-file/simplicity — rejected).

---

## 2. Git Fetch on Existing Bare Clone

**Decision**: Subprocess `git --git-dir <tmpdir> fetch --all` — same pattern as `_build_graph_from_git`.

**Rationale**: The backend already uses subprocess git for graph rendering. Fetch via subprocess is consistent, handles SSL env vars automatically (git reads `GIT_SSL_NO_VERIFY`), and avoids reimplementing Dulwich's fetch auth plumbing.

**Pattern**:
```python
subprocess.run(
    ["git", "--git-dir", self._tmpdir, "fetch", "--all", "--quiet"],
    capture_output=True,
)
```

**Alternatives considered**: `dulwich.porcelain.fetch(self._tmpdir, url)` — requires passing the auth URL back into the backend; more complex than subprocess for no gain.

---

## 3. Diff Summary and Unique Commits

**Decision**: Two subprocess calls on the bare clone.

```python
# File diff with per-file stats
git --git-dir <tmpdir> diff origin/<base> origin/<target> --stat --no-color

# Short summary line
git --git-dir <tmpdir> diff origin/<base> origin/<target> --shortstat --no-color

# Commits unique to target
git --git-dir <tmpdir> log origin/<base>..origin/<target> --oneline --format="%h %s %an %ad" --date=short
```

**Rationale**: These commands work fully with `filter=blob:none` (tree-level operations, no blob access). Subprocess keeps the same pattern as `_build_graph_from_git`.

**Alternatives considered**: Dulwich `tree_changes()` — already used in `get_detail()` for per-commit diffs, but assembling a cross-branch diff via Dulwich requires manual tree walking. Subprocess is simpler here.

---

## 4. Conflict Detection (Hunk-Level)

**Decision**: `git merge-tree --write-tree` (git ≥ 2.38) with fallback to classic `git merge-tree`.

**New format (preferred)**:
```bash
git --git-dir <tmpdir> -c core.bare=true merge-tree --write-tree --no-messages \
    origin/<base> origin/<target>
```
Exit code 1 = conflicts exist. Output lists conflicting files and conflict markers.

**Fallback (git < 2.38)**:
```bash
BASE=$(git --git-dir <tmpdir> merge-base origin/<base> origin/<target>)
git --git-dir <tmpdir> merge-tree $BASE origin/<base> origin/<target>
```
Parse output for `+<<<<<<` markers to find conflicting files.

**Blob availability**: `filter=blob:none` means blobs for conflicting files may not be local. `git merge-tree --write-tree` will auto-request missing blobs from the remote (via partial clone lazy fetch) when run against the bare clone. If the remote is unreachable, it falls back to file-level conflict detection only, with a note in the UI.

**Rationale**: `git merge-tree` works on bare repos, performs no actual merge, and outputs conflict markers without touching any branch. No new dependencies required.

**Alternatives considered**: Checking out both branches into a temp worktree and running `git merge --no-commit` — requires a non-bare working tree, violates simplicity, slower.

---

## 5. Shallow Clone + Missing Merge Base

**Decision**: Detect shallow state; show warning banner; display best-effort results.

**Detection**:
```bash
git --git-dir <tmpdir> rev-parse --is-shallow-repository
# returns "true" or "false"
```

If `merge-base` fails (exit code non-zero), the merge base is outside shallow history. In this case:
- Show: "⚠ Shallow clone — commit log and conflict results may be incomplete"
- Still show diff summary (works without merge base)
- Skip or partially show commit log / conflict section

---

## 6. Export Format

**Decision**: Plain `.txt` file written to the current working directory.

**Filename pattern**: `compare-{base}-{target}-{YYYYMMDD}.txt` with `/` replaced by `-` in branch names.

**Content structure**:
```
Compare: origin/{base} → origin/{target}
Generated: {datetime}

── Diff Summary ────────────────────
{shortstat line}

── Changed Files ───────────────────
{--stat output}

── Commits ({n}) ───────────────────
{log lines}

── Conflicts ───────────────────────
{conflict output or "Clean merge"}
```
