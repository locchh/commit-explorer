# Graph Rendering — Design, Problems & Fixes

## Overview

The app visualises a Git commit DAG fetched from the GitHub REST API.
`build_graph()` accepts a flat list of `CommitInfo` objects (each carrying
its `sha` and `parents` list), sorts them topologically, then feeds them
one-by-one into the `_Graph` state machine which produces one or more
`Rich.Text` lines per commit.  Those lines are displayed in the TUI via
Textual `Label` widgets.

---

## Architecture

```
GitHub REST API
  └── GET /repos/{owner}/{repo}/commits?per_page=100
        │
        ▼
  list[CommitInfo]          sha + parents[] from JSON
        │
        ▼
  _topo_sort()              children before parents, newest first
        │
        ▼
  _Graph state machine      mirrors git's graph.c
    states: PADDING → PRE_COMMIT → COMMIT → POST_MERGE → COLLAPSING
        │
        ▼
  list[tuple[CommitInfo, list[Rich.Text]]]
        │
        ▼
  CommitItem (Textual ListItem)
    ├── Label(graph_text)   Rich.Text, no markup parsing
    └── Label(info_cell)    Rich markup string
```

---

## The `_Graph` State Machine

Ported from `git/graph.c`.  Each call to `graph_update(commit)` advances
the state; repeated calls to `graph_next_line()` drain all lines for that
commit until `graph_is_commit_finished()` returns `True`.

| State | Lines produced | Characters |
|---|---|---|
| `PRE_COMMIT` | expansion rows for octopus merges | `\|` |
| `COMMIT` | the `*` node line | `* \| \\ /` |
| `POST_MERGE` | first connector row after a merge | `/ \| \\` |
| `COLLAPSING` | lane-convergence rows | `/ _ \|` |
| `PADDING` | idle continuation rows | `\|` |

Two screen columns per logical lane (character + space).

---

## Problems Encountered & How They Were Fixed

### 1. Rich markup tags appearing as literal text

**Symptom:** TUI showed `[red]* [/red]` instead of a coloured `*`.

**Root cause:** The original `_ch()` helper built strings like
`f"[{color}]{char}[/{color}]"`.  Rich's `markup.escape()` was called on
the character but not consistently.  Backslash characters in the string
caused Rich's markup parser to mis-interpret closing tags.  Textual's
`Label(markup=True)` then rendered the raw tag text.

**Fix:** Replace every markup string with `Rich.Text` objects.

```python
# Before (fragile)
def _ch(color_idx: int, char: str) -> str:
    c = _LANE_COLORS[color_idx % len(_LANE_COLORS)]
    return f"[{c}]{escape(char)}[/{c}]"

# After (robust)
def _ch(t: Text, color_idx: int, char: str) -> None:
    c = _LANE_COLORS[color_idx % len(_LANE_COLORS)]
    t.append(char, style=Style(color=c))
```

All `_output_*` methods in `_Graph` now receive and mutate a `Text` object
instead of building `list[str]`.  `CommitItem` passes the `Text` directly
to `Label` — no `markup=True` needed.

**Gotcha found during fix:** `Text.rstrip()` mutates in-place and returns
`None` (unlike `str.rstrip()`).  The original code did `return t.rstrip()`
which returned `None` and caused `AttributeError: 'NoneType' object has no
attribute 'style'` inside Textual.  Fixed by calling `t.rstrip()` then
`return t` separately.

---

### 2. Graph expanding with `\ \ \ \` instead of converging

**Symptom:** After each merge commit the graph grew one column wider
indefinitely — never collapsing back.

**Root cause:** Two sub-problems:

#### 2a. Parents outside the fetch window created orphan lanes

The `_update_columns()` method called `_insert_into_new_columns(parent_sha)`
for *every* parent SHA, including those not present in the fetched 100-commit
window.  Those parent SHAs never matched any future commit, so their lanes
drew `|` forever.

**Fix:** Added `known_shas: set[str]` to `_Graph`, populated in
`build_graph()` before rendering.  `_update_columns()` skips any parent not
in `known_shas`.  `num_parents` is also recalculated to count only
in-window parents.

```python
# In build_graph()
g.known_shas = {c.sha for c in commits}

# In _update_columns()
for p in self.commit.parents:
    if p not in self.known_shas:
        continue   # skip — no orphan lane
    self._insert_into_new_columns(p, i)
```

#### 2b. Topo sort placed all feature tips after all merges

When many merges shared the same timestamp (common in GitHub where PRs are
merged in bulk), Kahn's algorithm seeded all branch tips simultaneously.
The heap broke ties by sequence number — so `M4` (seq 0) beat `F4` (seq 4)
and all merges ran first, leaving all feature tips bunched at the end.

**Symptom in graph:** `M4 → M3 → M2 → M1 → F4 → F3 → F2 → F1 → base` —
the state machine saw a new unknown lane for each merge and kept widening.

**Fix:** Two-tier priority heap.  Non-first parents (feature branch tips)
get **tier 0** so they always sort before mainline commits (**tier 1**).
The tier is propagated through the feature branch chain so the entire
branch history drains before mainline resumes.

```python
# heap entry: (tier, neg_date, seq, sha)
# tier 0 = feature branch chain (drain first)
# tier 1 = mainline

if idx > 0:              # non-first parent → feature branch
    ptier = 0
    pdate = nd           # inherit parent merge's neg_date
elif tier == 0:          # continuing a feature branch chain
    ptier = 0
    pdate = _neg(by_sha[p].date)
else:                    # mainline first parent
    ptier = 1
    pdate = _neg(by_sha[p].date)
```

**Result:** Sort order now matches `git log` exactly for the test cases
validated against a local clone of `paperclipai/paperclip`.

---

### 3. Graph column width — overflow and clipping

**Symptom:** Graph was clipped at a fixed 8-character width.

**Fix:** Changed CSS to `width: auto` so the column sizes to its content:

```css
.graph-col { width: auto; min-width: 2; padding: 0 1 0 0; }
```

Removed `overflow-x: hidden` which was silently clipping wide graphs.

---

## Remaining Known Limitation

**Branches diverging before the fetch window** cannot be shown correctly.

The REST API returns at most 100 commits per request from the default
branch.  If a feature branch diverged more than 100 commits ago its
history is not in the window, so its parent SHA is unknown and the lane is
dropped.  This makes the graph look disconnected for old or long-running
branches.

### Proposed fix (TODO idea #2)

1. Call `GET /repos/{owner}/{repo}/branches` to get all branch tip SHAs.
2. For each tip SHA not already in the 100-commit window, fetch a small
   slice of that branch's history (e.g. 10 commits).
3. Merge all fetched commits (deduplicated by SHA) before calling
   `build_graph()`.

This ensures `known_shas` contains the convergence ancestors, so
`_update_columns()` correctly opens and closes lanes for all active
branches — without requiring a full clone.

**Trade-off:** N extra API requests (one per active branch).  For repos
with many branches this adds latency.  A sensible cap (e.g. fetch at most
5 branches beyond the default) keeps it practical.

---

## Test Patterns

Quick smoke-test to validate graph output without running the TUI:

```python
from app import build_graph, CommitInfo

def mk(sha, msg, date, parents):
    return CommitInfo(sha=sha, short_sha=sha[:7], message=msg,
                      author='u', author_email='u@x',
                      date=date, parents=parents)

commits = [
    mk('M2', 'merge2', '2024-01-04', ['M1', 'F2']),
    mk('F2', 'feat2',  '2024-01-03', ['M1']),
    mk('M1', 'merge1', '2024-01-02', ['B',  'F1']),
    mk('F1', 'feat1',  '2024-01-01', ['B']),
    mk('B',  'base',   '2024-01-00', []),
]

for commit, lines in build_graph(commits):
    for line in lines:
        print(line.plain)
```

Expected output (matches `git log --graph`):
```
*
|\
| *
*
|\
| *
*
```
